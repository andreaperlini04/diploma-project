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
use ReflectionMethod;

/**
 * Test della configurazione passata al modulo JavaScript.
 *
 * I metodi sotto esame sono privati e invocati per reflection: il loro
 * risultato confluisce in js_call_amd e non è altrimenti ispezionabile.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
#[\PHPUnit\Framework\Attributes\CoversClass(\local_eegimucapture\hook_callbacks::class)]
final class hook_callbacks_test extends advanced_testcase {

    protected function setUp(): void {
        parent::setUp();
        $this->resetAfterTest(true);
    }

    /**
     * Invoca il metodo privato page_context().
     *
     * @return array
     */
    private function page_context(): array {
        return (new ReflectionMethod(hook_callbacks::class, 'page_context'))->invoke(null);
    }

    /**
     * Invoca il metodo privato backend_url().
     *
     * @return string
     */
    private function backend_url(): string {
        return (new ReflectionMethod(hook_callbacks::class, 'backend_url'))->invoke(null);
    }

    /**
     * Fuori da un corso il contesto lascia nulli i campi di corso e attività.
     *
     * $PAGE->course non è mai null: senza corso impostato vale il corso di
     * sistema, che va tradotto in corso assente.
     */
    public function test_page_context_outside_a_course(): void {
        $context = $this->page_context();

        $this->assertNull($context['course_id']);
        $this->assertNull($context['course_name']);
        $this->assertNull($context['course_module_id']);
        $this->assertNull($context['module_type']);
        $this->assertNull($context['activity_name']);
        $this->assertNull($context['activity_instance_id']);
    }

    /**
     * In una pagina di corso il contesto riporta id e nome del corso.
     *
     * Regressione: $PAGE->course è risolto da __get() senza un __isset(),
     * quindi empty() e isset() lo darebbero sempre per non impostato.
     */
    public function test_page_context_in_a_course(): void {
        global $PAGE;

        $course = $this->getDataGenerator()->create_course(['fullname' => 'Corso Contesto']);

        $PAGE->set_url('/course/view.php', ['id' => $course->id]);
        $PAGE->set_course($course);

        $context = $this->page_context();

        $this->assertEquals($course->id, $context['course_id']);
        $this->assertSame('Corso Contesto', $context['course_name']);
        $this->assertNull($context['course_module_id']);
        $this->assertNull($context['module_type']);
        $this->assertNull($context['activity_name']);
    }

    /**
     * In una pagina di attività il contesto riporta anche tipo, nome e
     * istanza del modulo.
     *
     * Vale per $PAGE->cm la stessa considerazione su __get() descritta in
     * test_page_context_in_a_course.
     */
    public function test_page_context_in_an_activity(): void {
        global $PAGE;

        $course = $this->getDataGenerator()->create_course(['fullname' => 'Corso Attivita']);
        $page   = $this->getDataGenerator()->create_module('page', [
            'course' => $course->id,
            'name'   => 'Pagina Contesto',
        ]);

        $cm = get_coursemodule_from_instance('page', $page->id);

        $PAGE->set_url('/mod/page/view.php', ['id' => $cm->id]);
        $PAGE->set_cm($cm, $course);

        $context = $this->page_context();

        $this->assertEquals($course->id, $context['course_id']);
        $this->assertSame('Corso Attivita', $context['course_name']);
        $this->assertEquals($cm->id, $context['course_module_id']);
        $this->assertSame('page', $context['module_type']);
        $this->assertSame('Pagina Contesto', $context['activity_name']);
        $this->assertEquals($page->id, $context['activity_instance_id']);
    }

    /**
     * Il contesto riporta l'utente della richiesta corrente.
     */
    public function test_page_context_includes_the_current_user(): void {
        $user = $this->getDataGenerator()->create_user();
        $this->setUser($user);

        $context = $this->page_context();

        $this->assertSame((int)$user->id, $context['user_id']);
    }

    /**
     * Senza un utente autenticato il campo user_id resta nullo.
     */
    public function test_page_context_without_a_user(): void {
        $this->setUser(null);

        $context = $this->page_context();

        $this->assertNull($context['user_id']);
    }

    /**
     * In assenza di configurazione si usa l'endpoint canonico.
     *
     * get_config() restituisce false quando l'impostazione non esiste: senza
     * il ripiego, il client riceverebbe un URL vuoto e non invierebbe nulla.
     */
    public function test_backend_url_defaults_to_the_canonical_endpoint(): void {
        $this->assertStringEndsWith('/api/v1/events', $this->backend_url());
    }

    /**
     * Un URL configurato ha la precedenza sul valore predefinito.
     */
    public function test_backend_url_uses_the_configured_value(): void {
        set_config('backendurl', 'http://backend.test/api/v1/events', 'local_eegimucapture');

        $this->assertSame('http://backend.test/api/v1/events', $this->backend_url());
    }

    /**
     * Un valore configurato vuoto equivale ad assente e non deve produrre un
     * URL vuoto.
     */
    public function test_backend_url_falls_back_when_configured_value_is_empty(): void {
        set_config('backendurl', '', 'local_eegimucapture');

        $this->assertStringEndsWith('/api/v1/events', $this->backend_url());
    }
}
