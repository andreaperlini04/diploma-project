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
 * Punto di ingresso del plugin lato client.
 *
 * question_tracker rileva l'attività e produce messaggi interni, questo modulo
 * li converte negli envelope di POST /api/v1/events, transport li consegna in
 * batch, clock_skew misura lo sfasamento fra gli orologi.
 *
 * @module     local_eegimucapture/click_tracker
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
define([
    'local_eegimucapture/transport',
    'local_eegimucapture/clock_skew',
    'local_eegimucapture/question_tracker'
], function(transport, clockSkew, questionTracker) {

    /**
     * Copia superficiale di un oggetto.
     *
     * @param {Object} obj Oggetto da copiare.
     * @return {Object} Copia dell'oggetto.
     */
    function shallowCopy(obj) {
        var out = {};
        for (var k in obj) {
            if (obj.hasOwnProperty(k)) {
                out[k] = obj[k];
            }
        }
        return out;
    }

    /**
     * Identificativo del tentativo, dal parametro attempt della query string.
     *
     * @return {number|null} Identificativo, o null fuori da un tentativo.
     */
    function attemptIdFromUrl() {
        var m = window.location.search.match(/[?&]attempt=(\d+)/);
        return m ? (parseInt(m[1], 10) || null) : null;
    }

    /**
     * Determina l'event_type semantico a partire dal messaggio interno.
     *
     * I messaggi con chiave payload sono già classificati da un modello
     * semantico; gli altri sono interazioni di navigazione.
     *
     * @param {Object} msg Messaggio in formato interno.
     * @return {string} Valore di event_type per il backend.
     */
    function backendEventType(msg) {
        if (msg.payload && typeof msg.payload === 'object') {
            return msg.event_type;
        }
        if (msg.event_type === 'input_change') {
            return 'input_change';
        }
        return 'navigation_clicked';
    }

    /**
     * Converte un messaggio interno nell'envelope atteso dal backend.
     *
     * Normalizza le due forme prodotte da question_tracker e aggiunge il
     * contesto di pagina, così che ogni record sia interpretabile da solo.
     *
     * @param {Object} msg Messaggio in formato interno.
     * @param {Object} context Contesto di pagina fornito dal server.
     * @param {number|null} attemptId Identificativo del tentativo corrente.
     * @return {Object} Envelope per POST /api/v1/events.
     */
    function buildBackendEnvelope(msg, context, attemptId) {
        var eventType = backendEventType(msg);
        var payload;

        if (msg.payload && typeof msg.payload === 'object') {
            payload = shallowCopy(msg.payload);
        } else if (eventType === 'input_change') {
            payload = {
                target_tag:  msg.target_tag  || null,
                target_id:   msg.target_id   || null,
                target_type: msg.target_type || null
            };
        } else {
            // Per navigation_clicked il backend legge label, non target_text.
            payload = {
                target_tag: msg.target_tag  || null,
                label:      msg.target_text || null
            };
        }

        var ctx = shallowCopy(context);
        if (attemptId !== null) {
            ctx.attempt_id = attemptId;
        }
        payload.context = ctx;
        // origin distingue i due percorsi di acquisizione; source indica la
        // sorgente dei dati e vale sempre 'moodle'.
        payload.origin  = 'client';

        return {
            event_type:  eventType,
            payload:     payload,
            source:      'moodle',
            // Di primo livello e non solo in payload.context: è il solo modo di
            // attribuire l'evento con più partecipanti attivi insieme.
            user_id:     context.user_id || null,
            // Il backend calcola la descrizione quando riceve null.
            description: null,
            // ts_browser_ms è rilevato al momento dell'interazione: leggere qui
            // l'orologio misurerebbe anche il ritardo del buffer.
            timestamp:   msg.ts_browser_ms || Date.now()
        };
    }

    /**
     * Inoltra al backend gli eventi server-side accodati da PHP.
     *
     * Il timestamp è sul clock del server e viene riportato su quello locale
     * sottraendo lo skew. Lo skew è però quello della pagina corrente, mentre
     * l'evento può essere di minuti prima: ogni evento conserva quindi il
     * valore originale e l'entità della correzione, per il ricalcolo.
     *
     * @param {Array<Object>} events Eventi da inoltrare.
     * @param {string} backendUrl URL del backend.
     * @param {Object|null} skew Misura dello skew, o null se non disponibile.
     * @param {Object} context Contesto di pagina fornito dal server.
     * @return {void}
     */
    function relayServerEvents(events, backendUrl, skew, context) {
        var skewMs = skew ? skew.skew_ms : null;

        events.forEach(function(ev) {
            var correctedMs = (typeof skewMs === 'number')
                ? ev.timestamp_ms - skewMs
                : ev.timestamp_ms;

            transport.send(backendUrl, {
                event_type:  ev.event_type,
                payload:     Object.assign({}, ev.payload, {
                    raw_timestamp_ms:    ev.timestamp_ms,
                    skew_ms_applied:     (typeof skewMs === 'number') ? skewMs : null,
                    skew_uncertainty_ms: skew ? skew.uncertainty_ms : null,
                    relay_delay_ms:      Math.max(0, Math.round(Date.now() - correctedMs)),
                    origin:              'server'
                }),
                // La coda è per utente e viene svuotata per l'utente corrente,
                // quindi il contesto vale anche per gli eventi da cron.
                user_id:     context.user_id || null,
                description: null,
                source:      'moodle',
                timestamp:   Math.round(correctedMs)
            });
        });
    }

    return {
        /**
         * Inizializza il tracciamento sulla pagina corrente.
         *
         * @param {Object} config Configurazione fornita dal server:
         *     backendUrl, serverTimeUrl, context, serverEvents, testRecorder.
         * @return {void}
         */
        init: function(config) {

            var context   = config.context || {};
            var attemptId = attemptIdFromUrl();

            // Prima di qualsiasi invio, altrimenti i primi eventi della pagina
            // sfuggirebbero al registro.
            if (config.testRecorder) {
                transport.enableTestRecorder();
            }

            /**
             * Converte il messaggio in envelope e lo accoda per l'invio.
             *
             * @param {Object} payload Messaggio in formato interno.
             * @return {void}
             */
            function send(payload) {
                transport.send(
                    config.backendUrl,
                    buildBackendEnvelope(payload, context, attemptId)
                );
            }

            // Timestamp rilevato subito, invio rinviato al termine della misura
            // dello skew, per l'ordine page_loaded, clock_skew_measured, relay.
            var pageLoadedMsg = {
                event_type:    'page_loaded',
                payload:       {},
                ts_browser_ms: Date.now()
            };

            // Ogni round trip verso server_time.php comporta un bootstrap
            // Moodle completo: la misura dura complessivamente qualche secondo.
            clockSkew.measure(config.serverTimeUrl, 5).then(function(skew) {
                send(pageLoadedMsg);

                if (skew) {
                    send({
                        event_type:    'clock_skew_measured',
                        payload:       skew,
                        ts_browser_ms: Date.now()
                    });
                }

                if (config.serverEvents && config.serverEvents.length) {
                    relayServerEvents(
                        config.serverEvents,
                        config.backendUrl,
                        skew,
                        context
                    );
                }
            });

            questionTracker.initAll(send);

            // pagehide copre la back forward cache, dove beforeunload non viene
            // emesso; visibilitychange copre i dispositivi mobili, dove può non
            // essere emesso pagehide. Il flush usa sendBeacon: si veda
            // transport.flushOnExit.
            window.addEventListener('pagehide', transport.flushOnExit);
            document.addEventListener('visibilitychange', function() {
                if (document.visibilityState === 'hidden') {
                    transport.flushOnExit();
                }
            });
        }
    };
});
