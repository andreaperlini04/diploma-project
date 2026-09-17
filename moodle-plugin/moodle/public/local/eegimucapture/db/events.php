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
 * Observer degli eventi core sottoscritti dal plugin.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$observers = [
    [
        'eventname' => '\core\event\user_loggedin',
        'callback' => '\local_eegimucapture\observer::user_loggedin',
    ],
    [
        'eventname' => '\core\event\course_viewed',
        'callback' => '\local_eegimucapture\observer::course_viewed',
    ],
    [
        'eventname' => '\mod_quiz\event\attempt_started',
        'callback'  => '\local_eegimucapture\observer::quiz_attempt_started',
    ],
    [
        'eventname' => '\mod_quiz\event\attempt_submitted',
        'callback'  => '\local_eegimucapture\observer::quiz_attempt_submitted',
    ],
    [
        // course_module_viewed è astratta: Moodle instrada al callback anche
        // le sottoclassi concrete dei singoli moduli.
        'eventname' => '\core\event\course_module_viewed',
        'callback'  => '\local_eegimucapture\observer::activity_opened',
    ],
    [
        'eventname' => '\mod_quiz\event\attempt_abandoned',
        'callback'  => '\local_eegimucapture\observer::quiz_attempt_abandoned',
    ],
    [
        'eventname' => '\mod_quiz\event\attempt_becameoverdue',
        'callback'  => '\local_eegimucapture\observer::quiz_attempt_becameoverdue',
    ],
    [
        'eventname' => '\mod_quiz\event\attempt_reviewed',
        'callback'  => '\local_eegimucapture\observer::quiz_attempt_reviewed',
    ],
    [
        'eventname' => '\mod_lesson\event\lesson_started',
        'callback'  => '\local_eegimucapture\observer::lesson_started',
    ],
    [
        'eventname' => '\mod_lesson\event\lesson_ended',
        'callback'  => '\local_eegimucapture\observer::lesson_ended',
    ],
    [
        'eventname' => '\mod_assign\event\assessable_submitted',
        'callback'  => '\local_eegimucapture\observer::assignment_submitted',
    ],
    [
        'eventname' => '\mod_forum\event\post_created',
        'callback'  => '\local_eegimucapture\observer::forum_post_created',
    ],
    [
        'eventname' => '\mod_forum\event\discussion_viewed',
        'callback'  => '\local_eegimucapture\observer::forum_opened',
    ],
];
