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

/**
 * Step definition per local_eegimucapture.
 *
 * @package    local_eegimucapture
 * @category   test
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

require_once(__DIR__ . '/../../../../lib/behat/behat_base.php');

use Behat\Mink\Exception\ExpectationException;

/**
 * Verifica gli eventi prodotti dal client durante uno scenario Behat.
 *
 * Gli eventi del browser non lasciano traccia lato server e il backend non è
 * in esecuzione durante i test: il punto di osservazione è il registro in
 * sessionStorage di local_eegimucapture/transport, attivo sul solo sito Behat.
 *
 * Nessuna pulizia fra scenari: Moodle riavvia la sessione del browser prima di
 * ognuno e la sessionStorage riparte vuota.
 *
 * @package    local_eegimucapture
 * @category   test
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class behat_eegimucapture extends behat_base {

    /** @var string Chiave di sessionStorage usata dal registro. */
    private const STORAGE_KEY = 'eegimucapture_sent_events';

    /** @var int Secondi di attesa massima per la comparsa di un evento. */
    private const TIMEOUT = 10;

    /**
     * Verifica che il client abbia prodotto un evento del tipo indicato.
     *
     * @Then /^the eegimucapture client should have sent an event of type "(?P<type>[^"]*)"$/
     * @param string $type
     */
    public function the_client_should_have_sent_an_event_of_type($type) {
        $this->wait_for_matching_event(
            function(array $event) use ($type) {
                return $event['event_type'] === $type;
            },
            "No '$type' event was recorded before the timeout"
        );
    }

    /**
     * Verifica che il client abbia prodotto un evento del tipo indicato con
     * un determinato valore nel payload.
     *
     * @Then /^the eegimucapture client should have sent an event of type "(?P<type>[^"]*)" with payload "(?P<field>[^"]*)" "(?P<value>[^"]*)"$/
     * @param string $type
     * @param string $field
     * @param string $value
     */
    public function the_client_should_have_sent_an_event_of_type_with_payload($type, $field, $value) {
        $this->wait_for_matching_event(
            function(array $event) use ($type, $field, $value) {
                return $event['event_type'] === $type
                    && isset($event['payload'][$field])
                    && (string)$event['payload'][$field] === $value;
            },
            "No '$type' event with payload '$field'='$value' was recorded before the timeout"
        );
    }

    /**
     * Attende nel registro un evento che soddisfi il criterio.
     *
     * Il passo Behat può eseguire prima del gestore o prima che la navigazione
     * si concluda: si interroga ripetutamente invece di leggere una volta sola.
     *
     * @param callable $matches Criterio applicato a ciascun evento.
     * @param string $failuremessage Messaggio in caso di timeout.
     * @throws ExpectationException
     */
    private function wait_for_matching_event(callable $matches, string $failuremessage) {
        $start = microtime(true);

        while (microtime(true) - $start < self::TIMEOUT) {
            foreach ($this->get_recorded_events() as $event) {
                if (is_array($event) && isset($event['event_type']) && $matches($event)) {
                    return;
                }
            }
            usleep(300000);
        }

        throw new ExpectationException(
            $failuremessage . ' — ' . $this->describe_recorder_state(),
            $this->getSession()
        );
    }

    /**
     * Descrive lo stato del registro per distinguere le due cause di
     * fallimento: chiave assente significa recorder mai scritto, chiave
     * presente con altri tipi significa che manca solo l'evento atteso.
     *
     * @return string
     */
    private function describe_recorder_state(): string {
        $raw = $this->get_recorded_raw();

        if ($raw === null) {
            return 'the "' . self::STORAGE_KEY . '" key is absent from sessionStorage: '
                . 'the recorder never wrote anything';
        }

        $types = [];
        foreach ((json_decode($raw, true) ?: []) as $event) {
            $types[] = is_array($event) && isset($event['event_type'])
                ? $event['event_type'] : '?';
        }

        if (!$types) {
            return 'the recorder is present but empty';
        }

        return count($types) . ' events recorded: ' . implode(', ', $types);
    }

    /**
     * Contenuto grezzo del registro, o null se la chiave non esiste.
     *
     * Si distingue null dalla stringa vuota: sono le due diagnosi opposte.
     *
     * @return string|null
     */
    private function get_recorded_raw(): ?string {
        $value = $this->evaluate_script(
            'return window.sessionStorage.getItem("' . self::STORAGE_KEY . '");'
        );

        return $value === null ? null : (string)$value;
    }

    /**
     * Legge il registro degli envelope prodotti dal client.
     *
     * @return array
     */
    private function get_recorded_events(): array {
        $raw = $this->get_recorded_raw();

        return $raw === null ? [] : (json_decode($raw, true) ?: []);
    }
}
