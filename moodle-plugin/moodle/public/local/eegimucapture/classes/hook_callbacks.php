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

use core\hook\output\before_footer_html_generation;

defined('MOODLE_INTERNAL') || die();

/**
 * Implementazione dei callback degli hook del plugin.
 *
 * L'aggancio usa la hook API: il callback before_footer() di lib.php è
 * deprecato da Moodle 5.0 ed emette debugging() su ogni pagina, che fa fallire
 * gli scenari Behat.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class hook_callbacks {

    /**
     * URL predefinito del backend, sovrascrivibile con l'impostazione
     * backendurl del plugin.
     */
    private const DEFAULT_BACKEND_URL = 'http://localhost:8000/api/v1/events';

    /**
     * Carica click_tracker su ogni pagina con la configurazione per il client.
     *
     * @param before_footer_html_generation $hook
     */
    public static function before_footer_html_generation(before_footer_html_generation $hook): void {
        global $PAGE;

        $PAGE->requires->js_call_amd('local_eegimucapture/click_tracker', 'init', [
            [
                'backendUrl'    => self::backend_url(),
                'serverTimeUrl' => (new \moodle_url('/local/eegimucapture/server_time.php'))->out(false),
                'context'       => self::page_context(),
                'serverEvents'  => event_writer::drain_relay_queue(),
                // Gli eventi client non lasciano traccia lato server: sul sito
                // Behat si abilita un registro nel browser, unico punto di
                // osservazione dei test.
                'testRecorder'  => defined('BEHAT_SITE_RUNNING'),
            ],
        ]);
    }

    /**
     * URL del backend, con ripiego sul valore predefinito: get_config()
     * restituisce false quando l'impostazione non esiste.
     *
     * @return string
     */
    private static function backend_url(): string {
        $configured = get_config('local_eegimucapture', 'backendurl');
        return !empty($configured) ? $configured : self::DEFAULT_BACKEND_URL;
    }

    /**
     * Contesto della pagina corrente: utente, corso e attività.
     *
     * Incluso in ogni evento generato lato client. I campi non applicabili
     * restano null.
     *
     * @return array
     */
    private static function page_context(): array {
        global $PAGE, $USER;

        $context = [
            'user_id'              => null,
            'course_id'            => null,
            'course_name'          => null,
            'course_module_id'     => null,
            'module_type'          => null,
            'activity_name'        => null,
            'activity_instance_id' => null,
        ];

        // Su $USER, proprietà ordinarie: empty() si applica senza problemi.
        if (!empty($USER->id)) {
            $context['user_id'] = (int)$USER->id;
        }

        // Niente empty()/isset() su $PAGE->course e $PAGE->cm: risolte da
        // __get() senza __isset(), risulterebbero sempre non impostate.
        // Il corso di sistema (SITEID) va riportato come corso assente.
        if ($PAGE->course && (int)$PAGE->course->id !== (int)SITEID) {
            $context['course_id']   = (int)$PAGE->course->id;
            $context['course_name'] = $PAGE->course->fullname;
        }

        if ($PAGE->cm) {
            $context['course_module_id']     = (int)$PAGE->cm->id;
            $context['module_type']          = $PAGE->cm->modname;
            $context['activity_name']        = $PAGE->cm->name;
            $context['activity_instance_id'] = (int)$PAGE->cm->instance;
        }

        return $context;
    }
}
