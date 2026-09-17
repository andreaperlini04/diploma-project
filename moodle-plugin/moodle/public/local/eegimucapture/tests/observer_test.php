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
use context_course;
use context_module;
use core\event\user_loggedin;
use mod_quiz\event\attempt_submitted;
use mod_page\event\course_module_viewed as page_course_module_viewed;
use mod_forum\event\post_created;

/**
 * Test degli observer degli eventi core.
 *
 * Il punto di osservazione è la coda di relay, letta con drain_relay_queue()
 * dal dataroot PHPUnit, isolato e ripristinato dal framework. Ogni test invoca
 * setUser() prima di emettere l'evento.
 *
 * I campi minimi di ciascun evento derivano da validate_data() della rispettiva
 * classe; gli effetti collaterali degli handler core sono annotati nel test.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversClass(\local_eegimucapture\observer::class)]
final class observer_test extends advanced_testcase {

    protected function setUp(): void {
        parent::setUp();
        $this->resetAfterTest(true);
    }

    /**
     * Restituisce e svuota gli eventi accodati per l'utente corrente.
     *
     * @return array
     */
    private function get_relayed_entries(): array {
        return event_writer::drain_relay_queue();
    }

    /**
     * L'apertura di un corso produce course_opened con id e nome del corso.
     */
    public function test_course_viewed_writes_expected_event(): void {
        $course = $this->getDataGenerator()->create_course(['fullname' => 'Corso Test EEG']);
        $user   = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        // course_viewed non dichiara objecttable: passare objectid fa fallire
        // la validazione della classe base.
        $event = \core\event\course_viewed::create([
            'context'  => context_course::instance($course->id),
            'courseid' => $course->id,
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries, 'Nessun evento accodato nella coda di relay');

        $last = end($entries);
        $this->assertSame('course_opened', $last['event_type']);
        // assertEquals e non assertSame: a seconda del driver gli id tornano
        // come stringhe numeriche.
        $this->assertEquals($course->id, $last['payload']['course_id']);
        $this->assertSame('Corso Test EEG', $last['payload']['course_name']);
    }

    /**
     * L'avvio di un tentativo produce quiz_started con i dati del quiz e del
     * tentativo.
     */
    public function test_quiz_attempt_started_writes_expected_event(): void {
        // validate_data() richiede il solo relateduserid; other['quizid'] serve
        // al mapping in fase di ripristino.
        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('quiz', $quiz->id);

        $event = \mod_quiz\event\attempt_started::create([
            'objectid'      => 999,
            'relateduserid' => $user->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'quizid' => $quiz->id,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('quiz_started', $last['event_type']);
        $this->assertEquals($quiz->id, $last['payload']['quiz_id']);
        $this->assertSame('Quiz Test EEG', $last['payload']['quiz_name']);
        $this->assertEquals(999, $last['payload']['attempt_id']);
    }

    /**
     * Se il course module non è più presente, i campi che ne dipendono sono
     * null e l'evento viene comunque accodato.
     */
    public function test_quiz_attempt_started_when_course_module_deleted_writes_null_fields(): void {
        // Si elimina la sola riga di course_modules e non il context, che nel
        // funzionamento reale sopravvive fino al cleanup successivo: riproduce
        // lo stato in cui il cron elabora un evento su un modulo già rimosso.
        global $DB;

        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG Deleted',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm      = get_coursemodule_from_instance('quiz', $quiz->id);
        $context = context_module::instance($cm->id);

        $DB->delete_records('course_modules', ['id' => $cm->id]);

        $event = \mod_quiz\event\attempt_started::create([
            'objectid'      => 994,
            'relateduserid' => $user->id,
            'context'       => $context,
            'courseid'      => $course->id,
            'other'         => [
                'quizid' => $quiz->id,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('quiz_started', $last['event_type']);
        $this->assertNull($last['payload']['quiz_id']);
        $this->assertNull($last['payload']['quiz_name']);
        $this->assertEquals(994, $last['payload']['attempt_id']);
        $this->assertEquals($course->id, $last['payload']['course_id']);
    }

    /**
     * L'apertura di una discussione produce forum_opened con id del forum e
     * della discussione.
     */
    public function test_forum_opened_writes_expected_event(): void {
        // È necessaria una discussione reale: l'observer legge objectid come
        // identificativo della discussione.
        $course = $this->getDataGenerator()->create_course();
        $forum  = $this->getDataGenerator()->create_module('forum', [
            'course' => $course->id,
            'name'   => 'Forum Test EEG',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('forum', $forum->id);

        $discussion = $this->getDataGenerator()
            ->get_plugin_generator('mod_forum')
            ->create_discussion([
                'course' => $course->id,
                'forum'  => $forum->id,
                'userid' => $user->id,
            ]);

        $event = \mod_forum\event\discussion_viewed::create([
            'objectid' => $discussion->id,
            'context'  => context_module::instance($cm->id),
            'courseid' => $course->id,
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('forum_opened', $last['event_type']);
        $this->assertEquals($forum->id, $last['payload']['forum_id']);
        $this->assertEquals($discussion->id, $last['payload']['discussion_id']);
    }

    /**
     * L'abbandono di un tentativo produce quiz_abandoned.
     */
    public function test_quiz_attempt_abandoned_writes_expected_event(): void {
        // validate_data() richiede relateduserid; other['submitterid'] è
        // verificato con array_key_exists e ammette quindi null.
        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG Abandoned',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('quiz', $quiz->id);

        $event = \mod_quiz\event\attempt_abandoned::create([
            'objectid'      => 998,
            'relateduserid' => $user->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'quizid'      => $quiz->id,
                'submitterid' => $user->id,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('quiz_abandoned', $last['event_type']);
        $this->assertEquals($quiz->id, $last['payload']['quiz_id']);
        $this->assertSame('Quiz Test EEG Abandoned', $last['payload']['quiz_name']);
        $this->assertEquals(998, $last['payload']['attempt_id']);
    }

    /**
     * Un evento emesso dal cron è attribuito allo studente di relateduserid.
     *
     * Condizione di quiz_abandoned e quiz_overdue: nel cron $USER è l'utente di
     * sistema e l'evento finirebbe in una coda mai consultata dallo studente.
     */
    public function test_quiz_attempt_abandoned_is_queued_for_the_related_user(): void {
        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG Cron',
        ]);
        $student = $this->getDataGenerator()->create_user();
        $other   = $this->getDataGenerator()->create_user();

        $cm = get_coursemodule_from_instance('quiz', $quiz->id);

        // Evento emesso mentre è attivo un utente diverso dallo studente.
        $this->setUser($other);

        $event = \mod_quiz\event\attempt_abandoned::create([
            'objectid'      => 993,
            'relateduserid' => $student->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'quizid'      => $quiz->id,
                'submitterid' => $student->id,
            ],
        ]);
        $event->trigger();

        $this->assertSame([], $this->get_relayed_entries(),
            'L\'evento non deve finire nella coda dell\'utente della richiesta');

        $this->setUser($student);
        $entries = $this->get_relayed_entries();
        $this->assertCount(1, $entries);
        $this->assertSame('quiz_abandoned', $entries[0]['event_type']);
        $this->assertEquals(993, $entries[0]['payload']['attempt_id']);
    }

    /**
     * La scadenza del tempo di un tentativo produce quiz_overdue.
     */
    public function test_quiz_attempt_becameoverdue_writes_expected_event(): void {
        // validate_data() di attempt_becameoverdue ha gli stessi requisiti di
        // attempt_abandoned.
        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG Overdue',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('quiz', $quiz->id);

        $event = \mod_quiz\event\attempt_becameoverdue::create([
            'objectid'      => 997,
            'relateduserid' => $user->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'quizid'      => $quiz->id,
                'submitterid' => $user->id,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('quiz_overdue', $last['event_type']);
        $this->assertEquals($quiz->id, $last['payload']['quiz_id']);
        $this->assertSame('Quiz Test EEG Overdue', $last['payload']['quiz_name']);
        $this->assertEquals(997, $last['payload']['attempt_id']);
    }

    /**
     * La consultazione del riepilogo di un tentativo produce quiz_reviewed.
     */
    public function test_quiz_attempt_reviewed_writes_expected_event(): void {
        // Qui validate_data() verifica other['quizid'] con isset(): richiede un
        // valore non nullo, a differenza degli altri eventi di tentativo.
        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG Reviewed',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('quiz', $quiz->id);

        $event = \mod_quiz\event\attempt_reviewed::create([
            'objectid'      => 996,
            'relateduserid' => $user->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'quizid' => $quiz->id,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('quiz_reviewed', $last['event_type']);
        $this->assertEquals($quiz->id, $last['payload']['quiz_id']);
        $this->assertSame('Quiz Test EEG Reviewed', $last['payload']['quiz_name']);
        $this->assertEquals(996, $last['payload']['attempt_id']);
    }

    /**
     * L'avvio di una lezione produce lesson_started.
     */
    public function test_lesson_started_writes_expected_event(): void {
        // lesson_started non definisce una validate_data() propria e non
        // richiede né relateduserid né campi in other.
        $course = $this->getDataGenerator()->create_course();
        $user   = $this->getDataGenerator()->create_user();
        $this->setUser($user);
        // setUser prima di create_module: il generator di mod_lesson chiama
        // file_get_unused_draft_itemid(), che fallisce con l'utente ospite.
        $lesson = $this->getDataGenerator()->create_module('lesson', [
            'course' => $course->id,
            'name'   => 'Lesson Test EEG',
        ]);

        $cm = get_coursemodule_from_instance('lesson', $lesson->id);

        $event = \mod_lesson\event\lesson_started::create([
            'objectid' => $lesson->id,
            'context'  => context_module::instance($cm->id),
            'courseid' => $course->id,
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('lesson_started', $last['event_type']);
        $this->assertEquals($lesson->id, $last['payload']['lesson_id']);
        $this->assertSame('Lesson Test EEG', $last['payload']['lesson_name']);
    }

    /**
     * La conclusione di una lezione produce lesson_ended.
     */
    public function test_lesson_ended_writes_expected_event(): void {
        $course = $this->getDataGenerator()->create_course();
        $user   = $this->getDataGenerator()->create_user();
        $this->setUser($user);
        // Si veda test_lesson_started_writes_expected_event per l'ordine tra
        // setUser e create_module.
        $lesson = $this->getDataGenerator()->create_module('lesson', [
            'course' => $course->id,
            'name'   => 'Lesson Test EEG End',
        ]);

        $cm = get_coursemodule_from_instance('lesson', $lesson->id);

        $event = \mod_lesson\event\lesson_ended::create([
            'objectid' => $lesson->id,
            'context'  => context_module::instance($cm->id),
            'courseid' => $course->id,
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('lesson_ended', $last['event_type']);
        $this->assertEquals($lesson->id, $last['payload']['lesson_id']);
        $this->assertSame('Lesson Test EEG End', $last['payload']['lesson_name']);
    }

    /**
     * La consegna di un compito produce assignment_submitted.
     */
    public function test_assignment_submitted_writes_expected_event(): void {
        // validate_data() richiede other['submission_editable'] booleano.
        // objectid dovrebbe essere una riga di assign_submission, ma qui è
        // irrilevante: l'observer legge tutto dal course module.
        $course = $this->getDataGenerator()->create_course();
        $assign = $this->getDataGenerator()->create_module('assign', [
            'course' => $course->id,
            'name'   => 'Assign Test EEG',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('assign', $assign->id);

        $event = \mod_assign\event\assessable_submitted::create([
            'objectid'      => 1,
            'relateduserid' => $user->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'submission_editable' => true,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('assignment_submitted', $last['event_type']);
        $this->assertEquals($assign->id, $last['payload']['assign_id']);
        $this->assertSame('Assign Test EEG', $last['payload']['assign_name']);
    }

    /**
     * L'autenticazione di un utente produce user_loggedin.
     */
    public function test_user_loggedin_writes_expected_event(): void {
        // init() impone context_system e richiede other['username']; passare un
        // context esplicito produce "Context was already set in init()". Il
        // campo userid al trigger viene da $USER, non dall'objectid.
        $user = $this->getDataGenerator()->create_user(['username' => 'eeguser01']);
        $this->setUser($user);

        $event = user_loggedin::create([
            'objectid' => $user->id,
            'other'    => [
                'username' => $user->username,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('user_loggedin', $last['event_type']);
        $this->assertEquals($user->id, $last['payload']['user_id']);
        $this->assertSame('eeguser01', $last['payload']['username']);
    }

    /**
     * La consegna di un tentativo produce quiz_submitted.
     */
    public function test_quiz_attempt_submitted_writes_expected_event(): void {
        // mod_quiz registra un proprio handler che rilegge quiz_attempts da
        // objectid: un id inesistente provoca un accesso a proprietà su false,
        // da cui la riga reale. Lo stesso handler legge
        // other['studentisonline'], non documentato ma richiesto a runtime.
        global $DB;

        $course = $this->getDataGenerator()->create_course();
        $quiz   = $this->getDataGenerator()->create_module('quiz', [
            'course' => $course->id,
            'name'   => 'Quiz Test EEG Submitted',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('quiz', $quiz->id);

        $now = time();
        $attemptid = $DB->insert_record('quiz_attempts', (object)[
            'quiz'         => $quiz->id,
            'userid'       => $user->id,
            'attempt'      => 1,
            'uniqueid'     => 0,
            'layout'       => '',
            'currentpage'  => 0,
            'preview'      => 0,
            'state'        => 'finished',
            'timestart'    => $now,
            'timefinish'   => $now,
            'timemodified' => $now,
        ]);

        $event = attempt_submitted::create([
            'objectid'      => $attemptid,
            'relateduserid' => $user->id,
            'context'       => context_module::instance($cm->id),
            'courseid'      => $course->id,
            'other'         => [
                'quizid'          => $quiz->id,
                'submitterid'     => $user->id,
                'studentisonline' => false,
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('quiz_submitted', $last['event_type']);
        $this->assertEquals($quiz->id, $last['payload']['quiz_id']);
        $this->assertSame('Quiz Test EEG Submitted', $last['payload']['quiz_name']);
        $this->assertEquals($attemptid, $last['payload']['attempt_id']);
    }

    /**
     * L'apertura di un'attività produce activity_opened con tipo e nome del
     * modulo.
     */
    public function test_activity_opened_writes_expected_event(): void {
        // course_module_viewed è astratta: si usa la sottoclasse di mod_page.
        // L'observer è registrato sulla base e riceve anche le sottoclassi.
        $course = $this->getDataGenerator()->create_course();
        $page   = $this->getDataGenerator()->create_module('page', [
            'course' => $course->id,
            'name'   => 'Page Test EEG',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('page', $page->id);

        $event = page_course_module_viewed::create([
            'objectid' => $page->id,
            'context'  => context_module::instance($cm->id),
            'courseid' => $course->id,
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('activity_opened', $last['event_type']);
        $this->assertEquals($course->id, $last['payload']['course_id']);
        $this->assertEquals($cm->id, $last['payload']['course_module_id']);
        $this->assertSame('page', $last['payload']['module_type']);
        $this->assertSame('Page Test EEG', $last['payload']['activity_name']);
    }

    /**
     * La pubblicazione di un messaggio produce forum_post_created con
     * l'identificativo della discussione.
     */
    public function test_forum_post_created_writes_expected_event(): void {
        // validate_data() di post_created richiede other['discussionid'],
        // other['forumid'], other['forumtype'] e un context di modulo.
        $course = $this->getDataGenerator()->create_course();
        $forum  = $this->getDataGenerator()->create_module('forum', [
            'course' => $course->id,
            'name'   => 'Forum Test EEG Post',
        ]);
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $cm = get_coursemodule_from_instance('forum', $forum->id);

        $discussion = $this->getDataGenerator()
            ->get_plugin_generator('mod_forum')
            ->create_discussion([
                'course' => $course->id,
                'forum'  => $forum->id,
                'userid' => $user->id,
            ]);

        $event = post_created::create([
            'objectid' => 1,
            'context'  => context_module::instance($cm->id),
            'courseid' => $course->id,
            'other'    => [
                'discussionid' => $discussion->id,
                'forumid'      => $forum->id,
                'forumtype'    => 'general',
            ],
        ]);
        $event->trigger();

        $entries = $this->get_relayed_entries();
        $this->assertNotEmpty($entries);

        $last = end($entries);
        $this->assertSame('forum_post_created', $last['event_type']);
        $this->assertEquals($forum->id, $last['payload']['forum_id']);
        $this->assertSame('Forum Test EEG Post', $last['payload']['forum_name']);
        $this->assertEquals($discussion->id, $last['payload']['discussion_id']);
    }
}
