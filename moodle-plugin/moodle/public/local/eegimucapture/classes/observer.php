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

use core\event\course_module_viewed;
use core\event\course_viewed;
use core\event\user_loggedin;
use mod_forum\event\discussion_viewed;
use mod_quiz\event\attempt_started;
use mod_quiz\event\attempt_submitted;
use mod_quiz\event\attempt_abandoned;
use mod_quiz\event\attempt_becameoverdue;
use mod_quiz\event\attempt_reviewed;
use mod_lesson\event\lesson_started as lesson_started_event;
use mod_lesson\event\lesson_ended as lesson_ended_event;
use mod_assign\event\assessable_submitted;
use mod_forum\event\post_created;

defined('MOODLE_INTERNAL') || die();

/**
 * Traduzione degli eventi core di Moodle nei tipi di evento del plugin.
 *
 * Il course module è sempre ricaricato con get_coursemodule_from_id(), che
 * restituisce false se il modulo è stato eliminato prima dell'elaborazione
 * (possibile con gli observer invocati dal cron): ogni lettura ha quindi un
 * valore di ripiego. Il corso fa eccezione, get_course() solleva
 * dml_exception anziché restituire false.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class observer {

    /**
     * Gestisce l'autenticazione di un utente.
     *
     * @param user_loggedin $event
     */
    public static function user_loggedin(user_loggedin $event): void {
        $data = $event->get_data();
        event_writer::write('user_loggedin', [
            'user_id'  => $data['userid'],
            'username' => $data['other']['username'] ?? 'n/a',
        ]);
    }

    /**
     * Gestisce l'apertura di un corso.
     *
     * @param course_viewed $event
     * @throws \dml_exception Se il corso non esiste più.
     */
    public static function course_viewed(course_viewed $event): void {
        $data   = $event->get_data();
        $course = get_course($data['courseid']);
        event_writer::write('course_opened', [
            'course_id'   => $data['courseid'],
            'course_name' => $course->fullname ?? 'n/a',
        ]);
    }

    /**
     * Gestisce l'avvio di un tentativo di quiz.
     *
     * @param attempt_started $event
     */
    public static function quiz_attempt_started(attempt_started $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('quiz', $data['contextinstanceid']);
        event_writer::write('quiz_started', [
            'quiz_id'    => $cm ? $cm->instance : null,
            'quiz_name'  => $cm ? $cm->name     : null,
            'attempt_id' => $data['objectid'],
            'course_id'  => $data['courseid'],
        ]);
    }

    /**
     * Gestisce la consegna di un tentativo di quiz.
     *
     * @param attempt_submitted $event
     */
    public static function quiz_attempt_submitted(attempt_submitted $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('quiz', $data['contextinstanceid']);
        event_writer::write('quiz_submitted', [
            'quiz_id'    => $cm ? $cm->instance : null,
            'quiz_name'  => $cm ? $cm->name     : null,
            'attempt_id' => $data['objectid'],
            'course_id'  => $data['courseid'],
        ]);
    }

    /**
     * Gestisce l'apertura di un'attività.
     *
     * @param course_module_viewed $event
     */
    public static function activity_opened(course_module_viewed $event): void {
        $data = $event->get_data();
        $cmid = $data['contextinstanceid'];

        // Modulo non noto a priori: la stringa vuota lo fa risolvere dal
        // valore presente in course_modules.
        $cm = get_coursemodule_from_id('', $cmid);

        event_writer::write('activity_opened', [
            'course_id'        => $data['courseid'],
            'course_module_id' => $cmid,
            'module_type'      => $cm ? $cm->modname  : 'n/a',
            'activity_name'    => $cm ? $cm->name     : 'n/a',
        ]);
    }

    /**
     * Gestisce l'abbandono di un tentativo di quiz.
     *
     * @param attempt_abandoned $event
     */
    public static function quiz_attempt_abandoned(attempt_abandoned $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('quiz', $data['contextinstanceid']);
        event_writer::write('quiz_abandoned', [
            'quiz_id'    => $cm ? $cm->instance : null,
            'quiz_name'  => $cm ? $cm->name     : null,
            'attempt_id' => $data['objectid'],
            'course_id'  => $data['courseid'],
        ], null, self::attempt_userid($data));
    }

    /**
     * Gestisce la scadenza del tempo di un tentativo di quiz.
     *
     * @param attempt_becameoverdue $event
     */
    public static function quiz_attempt_becameoverdue(attempt_becameoverdue $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('quiz', $data['contextinstanceid']);
        event_writer::write('quiz_overdue', [
            'quiz_id'    => $cm ? $cm->instance : null,
            'quiz_name'  => $cm ? $cm->name     : null,
            'attempt_id' => $data['objectid'],
            'course_id'  => $data['courseid'],
        ], null, self::attempt_userid($data));
    }

    /**
     * Studente proprietario del tentativo di quiz.
     *
     * Nel cron $USER è l'utente di sistema: relateduserid indica l'utente
     * interessato dall'evento, userid chi lo ha innescato.
     *
     * @param array $data Dati restituiti da get_data() dell'evento.
     * @return int|null
     */
    private static function attempt_userid(array $data): ?int {
        $id = $data['relateduserid'] ?? $data['userid'] ?? null;
        return $id ? (int)$id : null;
    }

    /**
     * Gestisce la consultazione del riepilogo di un tentativo di quiz.
     *
     * @param attempt_reviewed $event
     */
    public static function quiz_attempt_reviewed(attempt_reviewed $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('quiz', $data['contextinstanceid']);
        event_writer::write('quiz_reviewed', [
            'quiz_id'    => $cm ? $cm->instance : null,
            'quiz_name'  => $cm ? $cm->name     : null,
            'attempt_id' => $data['objectid'],
            'course_id'  => $data['courseid'],
        ]);
    }

    /**
     * Gestisce l'avvio di una lezione.
     *
     * @param lesson_started_event $event
     */
    public static function lesson_started(lesson_started_event $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('lesson', $data['contextinstanceid']);
        event_writer::write('lesson_started', [
            'lesson_id'   => $cm ? $cm->instance : null,
            'lesson_name' => $cm ? $cm->name     : null,
            'course_id'   => $data['courseid'],
        ]);
    }

    /**
     * Gestisce la conclusione di una lezione.
     *
     * @param lesson_ended_event $event
     */
    public static function lesson_ended(lesson_ended_event $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('lesson', $data['contextinstanceid']);
        event_writer::write('lesson_ended', [
            'lesson_id'   => $cm ? $cm->instance : null,
            'lesson_name' => $cm ? $cm->name     : null,
            'course_id'   => $data['courseid'],
        ]);
    }

    /**
     * Gestisce la consegna di un compito.
     *
     * @param assessable_submitted $event
     */
    public static function assignment_submitted(assessable_submitted $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('assign', $data['contextinstanceid']);
        event_writer::write('assignment_submitted', [
            'assign_id'   => $cm ? $cm->instance : null,
            'assign_name' => $cm ? $cm->name     : null,
            'course_id'   => $data['courseid'],
        ]);
    }

    /**
     * Gestisce la pubblicazione di un messaggio in un forum.
     *
     * @param post_created $event
     */
    public static function forum_post_created(post_created $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('forum', $data['contextinstanceid']);
        // La discussione è in other['discussionid']: qui objectid è il
        // messaggio. In discussion_viewed la corrispondenza è invertita.
        event_writer::write('forum_post_created', [
            'forum_id'      => $cm ? $cm->instance : null,
            'forum_name'    => $cm ? $cm->name     : null,
            'discussion_id' => $data['other']['discussionid'] ?? null,
            'course_id'     => $data['courseid'],
        ]);
    }

    /**
     * Gestisce l'apertura di una discussione in un forum.
     *
     * @param discussion_viewed $event
     */
    public static function forum_opened(discussion_viewed $event): void {
        $data = $event->get_data();
        $cm   = get_coursemodule_from_id('forum', $data['contextinstanceid']);
        event_writer::write('forum_opened', [
            'forum_id'      => $cm ? $cm->instance : null,
            'forum_name'    => $cm ? $cm->name     : null,
            'discussion_id' => $data['objectid'] ?? null,
            'course_id'     => $data['courseid'],
        ]);
    }
}
