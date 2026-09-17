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

// Prima istruzione del file, da rilevare prima del bootstrap di Moodle, che
// costa circa un secondo: rilevata dopo, quella durata finirebbe in (t1 - t0)
// senza comparire fra i due tempi del server, e il client la leggerebbe come
// skew di circa rtt/2 anche senza sfasamento reale.
$server_recv_ms = microtime(true) * 1000;

/**
 * Riferimento temporale del server Moodle.
 *
 * Fornisce i due tempi lato server dello schema a quattro tempi usato dal
 * modulo clock_skew: ricezione e invio, la cui differenza è il tempo di
 * elaborazione. server_time_ms resta per i client privi di quello schema.
 *
 * @package    local_eegimucapture
 * @copyright  2026 Andrea Perlini <andreap0446@gmail.com>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

define('AJAX_SCRIPT', true);

require_once(__DIR__ . '/../../config.php');

require_login();

header('Content-Type: application/json');
header('Cache-Control: no-store, no-cache, must-revalidate');

$server_send_ms = microtime(true) * 1000;

echo json_encode([
    'server_recv_ms' => (int)$server_recv_ms,
    'server_send_ms' => (int)$server_send_ms,
    'server_time_ms' => (int)$server_send_ms,
]);
