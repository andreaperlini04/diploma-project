<?php
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

namespace local_eegimucapture;

defined('MOODLE_INTERNAL') || die();

/**
 * Emissione degli eventi server-side.
 *
 * Gli eventi sono accodati su file, una coda per utente in $CFG->dataroot, e
 * consegnati al backend dal modulo click_tracker alla prima pagina aperta
 * dallo studente. Il lato server non effettua richieste HTTP.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class event_writer {

    /**
     * Accoda un evento server-side per la consegna al backend.
     *
     * @param string $event_type Tipo semantico, in snake_case.
     * @param array $payload Dati specifici dell'evento.
     * @param int|null $timestamp_ms Millisecondi UNIX; se null, da microtime().
     *      Non time(): il vincolo di unicità del backend include ts, e a
     *      risoluzione di un secondo gli eventi omonimi collidono in silenzio.
     * @param int|null $userid Destinatario della coda; se null, l'utente
     *      corrente. Esplicito per gli eventi da cron, dove $USER è di sistema.
     */
    public static function write(
        string $event_type,
        array  $payload      = [],
        ?int   $timestamp_ms = null,
        ?int   $userid       = null
    ): void {
        // round() e non un cast: il troncamento darebbe un errore per difetto
        // costante, che non si media su molti eventi.
        $ts = $timestamp_ms ?? (int) round(microtime(true) * 1000);

        self::enqueue_for_relay($event_type, $payload, $ts, $userid);
    }

    /**
     * Percorso del file di coda di un utente, in $CFG->dataroot.
     *
     * @param int $userid
     * @return string
     */
    private static function relay_queue_path(int $userid): string {
        global $CFG;
        return $CFG->dataroot . '/local_eegimucapture_relay_' . $userid . '.json';
    }

    /**
     * Aggiunge un evento alla coda di relay dell'utente indicato.
     *
     * Coda su file e non in $SESSION: durante la correzione automatica di un
     * tentativo la sessione è chiusa in scrittura e le scritture successive
     * sono scartate in silenzio, perdendo quiz_submitted.
     *
     * @param string $event_type
     * @param array $payload
     * @param int $timestamp_ms
     * @param int|null $userid
     */
    private static function enqueue_for_relay(
        string $event_type,
        array  $payload,
        int    $timestamp_ms,
        ?int   $userid = null
    ): void {
        global $USER;

        $target = $userid;
        if ($target === null) {
            // In CLI e nel cron $USER non è lo studente. PHPUnit è escluso:
            // lì $USER è controllato da setUser() ed è il punto di
            // osservazione dei test.
            if (defined('CLI_SCRIPT') && CLI_SCRIPT
                    && !(defined('PHPUNIT_TEST') && PHPUNIT_TEST)) {
                return;
            }
            if (!empty($USER->id) && !(function_exists('isguestuser') && isguestuser())) {
                $target = (int)$USER->id;
            }
        }
        if (empty($target)) {
            return;
        }

        $entry = [
            'event_type'   => $event_type,
            'payload'      => $payload,
            'timestamp_ms' => $timestamp_ms,
        ];

        // 'c+' non tronca all'apertura: consente di prendere il lock prima di
        // leggere, evitando che richieste concorrenti si sovrascrivano.
        $fh = @fopen(self::relay_queue_path($target), 'c+');
        if ($fh === false) {
            return;
        }
        if (flock($fh, LOCK_EX)) {
            $raw   = stream_get_contents($fh);
            $queue = $raw !== '' ? (json_decode($raw, true) ?: []) : [];
            $queue[] = $entry;

            ftruncate($fh, 0);
            rewind($fh);
            fwrite($fh, json_encode($queue, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
            fflush($fh);
            flock($fh, LOCK_UN);
        }
        fclose($fh);
    }

    /**
     * Restituisce e svuota la coda dell'utente corrente.
     *
     * Lo svuotamento evita di riconsegnare gli stessi eventi a ogni pagina.
     *
     * @return array
     */
    public static function drain_relay_queue(): array {
        global $USER;

        if (empty($USER->id)) {
            return [];
        }
        $path = self::relay_queue_path((int)$USER->id);
        if (!file_exists($path)) {
            return [];
        }

        $queue = [];
        $fh = @fopen($path, 'c+');
        if ($fh === false) {
            return [];
        }
        if (flock($fh, LOCK_EX)) {
            $raw   = stream_get_contents($fh);
            $queue = $raw !== '' ? (json_decode($raw, true) ?: []) : [];

            ftruncate($fh, 0);
            fflush($fh);
            flock($fh, LOCK_UN);
        }
        fclose($fh);

        return $queue;
    }
}
