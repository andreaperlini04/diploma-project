// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <http://www.gnu.org/licenses/>.

/**
 * Consegna degli eventi al backend (POST /api/v1/events).
 *
 * Gli envelope sono accumulati in un buffer e inviati in batch. Il vincolo di
 * unicità del backend rende il reinvio idempotente, quindi il ritentativo dopo
 * un errore transitorio non produce duplicati.
 *
 * Il modulo non conosce la struttura degli envelope.
 *
 * @module     local_eegimucapture/transport
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
define([], function() {

    // Deliberatamente breve: una pagina può vivere meno dell'intervallo, e in
    // quel caso il timer non scatterebbe mai. Misurato su un compito N-back con
    // domande da 3 s, a 5 s si perdeva circa il 60% degli eventi.
    var FLUSH_INTERVAL_MS = 1000;

    // Oltre la soglia si svuota senza attendere il timer.
    var FLUSH_THRESHOLD_EVENTS = 10;

    // Limita l'uso di memoria se il backend resta a lungo irraggiungibile.
    var MAX_BUFFER_EVENTS = 500;

    var eventBuffer = [];
    var flushTimer  = null;
    var flushUrl    = null;

    // sessionStorage e non una variabile di modulo: il registro deve
    // sopravvivere ai cambi di pagina, perché gli scenari sui click di
    // navigazione asseriscono a pagina successiva già caricata.
    var TEST_STORAGE_KEY = 'eegimucapture_sent_events';

    var testRecorderActive = false;

    /**
     * Accumula l'envelope nel registro di test, se attivo.
     *
     * Gli eventi client non lasciano traccia lato server: durante i test il
     * registro è l'unico punto di osservazione. Gli errori sono ignorati, un
     * malfunzionamento del recorder non deve bloccare la consegna.
     *
     * @param {Object} envelope Envelope accodato per l'invio.
     * @return {void}
     */
    function recordForTests(envelope) {
        if (!testRecorderActive) {
            return;
        }
        try {
            var raw  = window.sessionStorage.getItem(TEST_STORAGE_KEY);
            var list = raw ? JSON.parse(raw) : [];
            list.push(envelope);
            window.sessionStorage.setItem(TEST_STORAGE_KEY, JSON.stringify(list));
        } catch (e) {
            return;
        }
    }

    /**
     * Segnala gli eventi ricevuti ma non salvati dal backend.
     *
     * Il backend risponde 201 anche quando scarta parte del batch, quindi lo
     * scarto non sarebbe altrimenti osservabile. duplicates non si segnala: con
     * il reinvio idempotente è un esito atteso.
     *
     * @param {Object|null} summary Riepilogo restituito dal backend.
     * @param {number} sent Numero di eventi nel batch inviato.
     * @return {void}
     */
    function warnOnDroppedEvents(summary, sent) {
        if (!summary || !window.console || !window.console.warn) {
            return;
        }
        var invalid = summary.invalid || 0;
        var noTs    = summary.no_timestamp || 0;
        if (invalid || noTs) {
            window.console.warn(
                '[eegimucapture] ' + (invalid + noTs) + ' eventi su ' + sent +
                ' scartati dal backend (invalid: ' + invalid +
                ', no_timestamp: ' + noTs + ')',
                summary
            );
        }
    }

    /**
     * Reinserisce un batch in testa al buffer per un nuovo tentativo.
     *
     * Solo per fallimenti transitori: un 4xx verrebbe rifiutato identico a ogni
     * tentativo e bloccherebbe la coda. L'inserimento in testa preserva
     * l'ordine rispetto agli eventi accumulati durante il tentativo fallito.
     *
     * @param {Array<Object>} batch Batch da reinserire.
     * @return {void}
     */
    function requeue(batch) {
        eventBuffer = batch.concat(eventBuffer);

        var overflow = eventBuffer.length - MAX_BUFFER_EVENTS;
        if (overflow > 0) {
            // Si scartano i più vecchi, con segnalazione: la perdita è
            // esplicita e non silenziosa.
            eventBuffer = eventBuffer.slice(overflow);
            if (window.console && window.console.warn) {
                window.console.warn(
                    '[eegimucapture] buffer pieno: ' + overflow +
                    ' eventi più vecchi scartati'
                );
            }
        }

        if (!flushTimer) {
            flushTimer = window.setTimeout(flushEvents, FLUSH_INTERVAL_MS);
        }
    }

    /**
     * Invia il contenuto del buffer in una singola POST.
     *
     * fetch con keepalive e non sendBeacon: sendBeacon non espone né gli errori
     * né il corpo della risposta.
     *
     * @return {void}
     */
    function flushEvents() {
        if (flushTimer) {
            window.clearTimeout(flushTimer);
            flushTimer = null;
        }
        if (!flushUrl || !eventBuffer.length) {
            return;
        }

        // Svuotato prima della fetch: un evento emesso durante la richiesta
        // entra nel batch successivo, non in quello già in volo.
        var batch = eventBuffer;
        eventBuffer = [];

        fetch(flushUrl, {
            method:  'POST',
            headers: {'Content-Type': 'application/json'},
            body:    JSON.stringify(batch),
            mode:      'cors',
            keepalive: true
        }).then(
            function(response) {
                // fetch risolve anche sugli status di errore: senza il
                // controllo, un batch rifiutato risulterebbe inviato.
                if (!response.ok) {
                    if (window.console && window.console.warn) {
                        window.console.warn(
                            '[eegimucapture] batch di ' + batch.length +
                            ' eventi rifiutato: HTTP ' + response.status
                        );
                    }
                    if (response.status >= 500) {
                        requeue(batch);
                    }
                    return null;
                }
                // Una 201 senza corpo JSON non è un errore.
                return response.json().catch(function() {
                    return null;
                });
            },
            function(err) {
                // Errori di trasporto. Gestito come secondo argomento di then()
                // e non con un catch finale, per non reinviare il batch se è il
                // ramo di successo a sollevare.
                if (window.console && window.console.warn) {
                    window.console.warn('[eegimucapture] backend non raggiungibile:', err);
                }
                requeue(batch);
                return null;
            }
        ).then(function(summary) {
            warnOnDroppedEvents(summary, batch.length);
        });
    }

    /**
     * Svuota il buffer con sendBeacon, per l'uscita dalla pagina.
     *
     * fetch qui non è utilizzabile: l'invio è cross-origin con Content-Type
     * application/json e richiede un preflight, che il browser non avvia su un
     * documento in smontaggio. La richiesta non parte e la promise non si
     * risolve mai, quindi la perdita è silenziosa. Il tipo text/plain è
     * obbligatorio per restare fra le richieste senza preflight: il backend
     * deve interpretare il corpo come JSON a prescindere dal Content-Type.
     *
     * sendBeacon riporta solo se il browser ha accettato di accodare la
     * richiesta, non l'esito del salvataggio.
     *
     * @return {void}
     */
    function flushWithBeacon() {
        if (flushTimer) {
            window.clearTimeout(flushTimer);
            flushTimer = null;
        }
        if (!flushUrl || !eventBuffer.length) {
            return;
        }
        if (!window.navigator || !window.navigator.sendBeacon) {
            flushEvents();
            return;
        }

        var batch = eventBuffer;
        eventBuffer = [];

        var payload = new Blob([JSON.stringify(batch)], {type: 'text/plain'});

        if (!window.navigator.sendBeacon(flushUrl, payload)) {
            // Coda del browser piena o payload oltre il limite. Gli eventi
            // tornano nel buffer, che però non sopravvivrà alla pagina.
            eventBuffer = batch.concat(eventBuffer);
            if (window.console && window.console.warn) {
                window.console.warn(
                    '[eegimucapture] sendBeacon ha rifiutato ' + batch.length +
                    ' eventi in uscita dalla pagina'
                );
            }
        }
    }

    return {
        /**
         * Accoda un envelope per il prossimo flush.
         *
         * @param {string} url URL del backend.
         * @param {Object} envelope Envelope da inviare.
         * @return {void}
         */
        send: function(url, envelope) {
            // Registrazione prima del controllo sull'URL: ai test interessa che
            // l'envelope sia stato prodotto, non che il backend sia configurato.
            recordForTests(envelope);

            if (!url) {
                return;
            }
            flushUrl = url;
            eventBuffer.push(envelope);

            if (eventBuffer.length >= FLUSH_THRESHOLD_EVENTS) {
                flushEvents();
                return;
            }
            if (!flushTimer) {
                flushTimer = window.setTimeout(flushEvents, FLUSH_INTERVAL_MS);
            }
        },

        /**
         * Svuota il buffer a pagina viva, con fetch.
         *
         * @return {void}
         */
        flush: flushEvents,

        /**
         * Svuota il buffer in uscita dalla pagina, con sendBeacon.
         *
         * @return {void}
         */
        flushOnExit: flushWithBeacon,

        /**
         * Attiva il registro degli envelope inviati. Solo per i test.
         *
         * @return {void}
         */
        enableTestRecorder: function() {
            testRecorderActive = true;
        }
    };
});
