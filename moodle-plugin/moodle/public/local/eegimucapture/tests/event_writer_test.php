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

use advanced_testcase;

/**
 * Test del contratto di event_writer.
 *
 * I metodi sono invocati direttamente: l'integrazione con gli eventi core è
 * verificata da observer_test. Il punto di osservazione è la coda di relay,
 * unico effetto prodotto da write().
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversClass(\local_eegimucapture\event_writer::class)]
final class event_writer_test extends advanced_testcase {

    protected function setUp(): void {
        parent::setUp();
        $this->resetAfterTest(true);
    }

    /**
     * Un evento accodato conserva tipo, payload e timestamp, e non include
     * una descrizione.
     */
    public function test_write_enqueues_expected_entry(): void {
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        event_writer::write('course_opened', [
            'course_id'   => 42,
            'course_name' => 'Corso Test',
        ]);

        $entries = event_writer::drain_relay_queue();
        $this->assertCount(1, $entries);

        $entry = $entries[0];
        $this->assertSame('course_opened', $entry['event_type']);
        $this->assertSame(['course_id' => 42, 'course_name' => 'Corso Test'], $entry['payload']);
        $this->assertIsInt($entry['timestamp_ms']);
        // Le descrizioni sono generate dal backend.
        $this->assertArrayNotHasKey('description', $entry);
    }

    /**
     * Un timestamp fornito esplicitamente non viene sovrascritto.
     */
    public function test_write_respects_explicit_timestamp_ms(): void {
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        event_writer::write('course_opened', ['course_id' => 1], 1700000000123);

        $entries = event_writer::drain_relay_queue();
        $this->assertSame(1700000000123, $entries[0]['timestamp_ms']);
    }

    /**
     * Gli eventi accodati mantengono l'ordine di emissione.
     */
    public function test_write_appends_multiple_entries_in_order(): void {
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        event_writer::write('course_opened', ['course_id' => 1]);
        event_writer::write('course_opened', ['course_id' => 2]);

        $entries = event_writer::drain_relay_queue();
        $this->assertCount(2, $entries);
        $this->assertSame(1, $entries[0]['payload']['course_id']);
        $this->assertSame(2, $entries[1]['payload']['course_id']);
    }

    /**
     * La lettura della coda ne comporta lo svuotamento, condizione
     * necessaria per non riconsegnare gli stessi eventi alle pagine
     * successive.
     */
    public function test_drain_empties_the_queue(): void {
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        event_writer::write('course_opened', ['course_id' => 1]);

        $this->assertCount(1, event_writer::drain_relay_queue());
        $this->assertSame([], event_writer::drain_relay_queue());
    }

    /**
     * Con un userid esplicito l'evento è attribuito a quell'utente e non a
     * quello della richiesta corrente, come per gli eventi da cron.
     */
    public function test_write_with_explicit_userid_targets_that_users_queue(): void {
        $student = $this->getDataGenerator()->create_user();
        $other   = $this->getDataGenerator()->create_user();

        $this->setUser($other);
        event_writer::write('quiz_overdue', ['quiz_id' => 7], null, (int)$student->id);

        $this->assertSame([], event_writer::drain_relay_queue());

        $this->setUser($student);
        $entries = event_writer::drain_relay_queue();
        $this->assertCount(1, $entries);
        $this->assertSame('quiz_overdue', $entries[0]['event_type']);
    }

    /**
     * In assenza sia di un utente in sessione sia di un userid esplicito non
     * esiste un destinatario e l'evento viene ignorato.
     */
    public function test_write_without_user_is_a_noop(): void {
        $this->setUser(null);

        event_writer::write('course_opened', ['course_id' => 1]);

        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);
        $this->assertSame([], event_writer::drain_relay_queue());
    }
}
