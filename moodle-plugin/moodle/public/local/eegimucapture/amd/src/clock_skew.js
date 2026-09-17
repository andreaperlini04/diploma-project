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
 * Stima dello sfasamento fra il clock del server Moodle e quello della
 * macchina locale, su cui sono allineati browser, backend e acquisizione EEG.
 *
 * @module     local_eegimucapture/clock_skew
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
define([], function() {

    /**
     * Stima lo sfasamento fra il clock del server e quello locale.
     *
     * Schema a quattro tempi analogo a NTP, con t0 e t1 letti in locale
     * all'invio e alla ricezione:
     *
     *     skew = ((server_recv - t0) + (server_send - t1)) / 2
     *
     * Il tempo di elaborazione compare nei due termini con segno opposto e si
     * elide: resta il solo errore da asimmetria dei ritardi, al più rtt/2. Uno
     * schema a due tempi lo attribuirebbe invece tutto alla rete, con un errore
     * sistematico di circa mezzo secondo dato il bootstrap Moodle.
     *
     * Si sceglie il campione con RTT di rete minimo, (t1 - t0) meno
     * l'elaborazione: minore accodamento implica ritardi più simmetrici. Il
     * totale (t1 - t0) non serve, è dominato dal bootstrap.
     *
     * Skew positivo indica clock del server in anticipo.
     *
     * @param {string} url URL di server_time.php.
     * @param {number} sampleCount Numero di round trip da eseguire.
     * @return {Promise<Object|null>} Stima dello skew, o null se non misurabile.
     */
    function measure(url, sampleCount) {
        var samples = [];

        /**
         * Esegue un singolo round trip e accumula il campione.
         *
         * @return {Promise} Promise risolta a misura completata.
         */
        function once() {
            var t0 = Date.now();
            return fetch(url, {cache: 'no-store', credentials: 'same-origin'})
                .then(function(response) {
                    return response.json();
                })
                .then(function(data) {
                    var t1 = Date.now();

                    if (typeof data.server_recv_ms === 'number' &&
                        typeof data.server_send_ms === 'number') {
                        var processing = data.server_send_ms - data.server_recv_ms;
                        var netRtt = Math.max(0, (t1 - t0) - processing);
                        samples.push({
                            rtt:        netRtt,
                            processing: processing,
                            skew: ((data.server_recv_ms - t0) +
                                (data.server_send_ms - t1)) / 2
                        });
                        return;
                    }

                    if (typeof data.server_time_ms === 'number') {
                        // Ripiego per le versioni di server_time.php prive dei
                        // tempi recv/send.
                        var rtt = t1 - t0;
                        samples.push({
                            rtt:        rtt,
                            processing: null,
                            skew:       data.server_time_ms - (t0 + rtt / 2)
                        });
                    }
                });
        }

        var chain = Promise.resolve();
        for (var i = 0; i < sampleCount; i++) {
            chain = chain.then(once);
        }

        return chain.then(function() {
            if (!samples.length) {
                return null;
            }
            var best = samples[0];
            for (var j = 1; j < samples.length; j++) {
                if (samples[j].rtt < best.rtt) {
                    best = samples[j];
                }
            }
            return {
                skew_ms:              Math.round(best.skew),
                uncertainty_ms:       Math.max(1, Math.round(best.rtt / 2)),
                rtt_min_ms:           best.rtt,
                server_processing_ms: best.processing !== null
                    ? Math.round(best.processing) : null,
                samples:              samples.length
            };
        }).catch(function() {
            return null;
        });
    }

    return {
        measure: measure
    };
});
