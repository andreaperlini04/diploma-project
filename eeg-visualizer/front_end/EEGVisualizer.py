"""
Visualizzatore EEG real-time per il dispositivo IDUN Guardian.

EEGVisualizer e' composta per mixin. Restano qui lo stato dell'istanza, il
ciclo di vita della registrazione e gli handler dei segnali Qt.

    config             costanti sperimentali condivise
    clock_sync         offset e deriva tra clock EEG e orologio macchina
    backend_client     apertura sessione, verifica NTP, invio campioni
    signal_processing  potenze di banda via Welch, gating, CSV
    ui_builder         layout PyQt6 e assi matplotlib
"""

import csv
import os
import sys
import time
from collections import Counter, deque
from datetime import datetime

# numpy resta importato qui anche se non usato direttamente in questo
# modulo: main.py lo ottiene tramite "from front_end.EEGVisualizer import *".
import numpy as np
from PyQt6 import QtCore, QtWidgets
# QPixmap e' usato dal codice dei classificatori attualmente commentato.
from PyQt6.QtGui import QIcon, QPixmap

from .backend_client import BackendClientMixin
from .clock_sync import ClockSyncMixin
from .config import (
    CLI_SMOOTHING_SECONDS,
    LOG_DIR,
    PLOT_WINDOW_SECONDS,
    QUALITY_SCORE_THRESHOLD,
    brainwave_bands,
    image_size,
    window_size_fft,
    window_size_imu,
    window_size_signal,
)
from .signal_processing import SignalProcessingMixin
from .ui_builder import UIBuilderMixin


class EEGVisualizer(
    ClockSyncMixin,
    BackendClientMixin,
    SignalProcessingMixin,
    UIBuilderMixin,
    QtWidgets.QWidget,
):
    """
    Finestra di visualizzazione real-time e coordinatore della registrazione.

    Tiene lo stato condiviso dai mixin, che non ne hanno di proprio: ognuno
    legge e scrive per nome gli attributi definiti in __init__.

    I flag dei classificatori (jaw_clench_detected, heog_*_detected) e i
    relativi hold timer restano definiti ma non vengono mai aggiornati: la
    visualizzazione dei classificatori e' disattivata.
    """
    signal_update = QtCore.pyqtSignal(list, object)
    prediction_update = QtCore.pyqtSignal(object, bool, bool, bool, object)
    impedance_update = QtCore.pyqtSignal(float)
    device_connected_update = QtCore.pyqtSignal(bool)
    # Emesso dal thread di upload, ricevuto nel thread GUI: unico modo sicuro
    # di aggiornare i widget da un altro thread.
    upload_status_update = QtCore.pyqtSignal(bool, str)

    def __init__(self, plot_FFT=False, on_close=None):
        super().__init__()
        self.IMPEDANCE_THRESHOLD = 300000
        self.on_close = on_close
        self.signal_update.connect(self.update_signals_visuals)
        self.prediction_update.connect(self.update_predictions_visuals)
        self.impedance_update.connect(self.update_impedance_visuals)
        self.device_connected = False
        self.device_connected_update.connect(self.update_device_connected_visuals)
        self.upload_status_update.connect(self.update_upload_visuals)
        self.plot_FFT = plot_FFT

        # Sentinella "dispositivo non connesso": tiene Start bloccato finche'
        # non arriva la prima misura.
        self.impedance_data = sys.maxsize
        # Coppie (timestamp EEG, ch1).
        self.signal_data = deque(maxlen=window_size_signal)
        #self.signal_data.extend([(0, 0) for _ in range(window_size_signal)])
        self.jaw_clench_detected = False
        self.heog_left_detected = False
        self.heog_right_detected = False

        # Quality score
        self.quality_score = deque(maxlen=window_size_fft)
        #self.quality_score.extend([0 for _ in range(window_size_fft)])
        self.quality_history = deque(maxlen=30)
        
        # Marcatore dell'ultimo calo di qualita': aggiornato ma non ancora
        # letto da nessuno, il filtro lo fa window_quality_ok.
        self.buffer_valid_from_ts = None

        # FFT data
        if plot_FFT:
            self.fft_keys = ['Delta', 'Theta', 'Alpha', 'Beta', 'Gamma', 'Sigma']
            self.fft_dict = {key: deque(maxlen=window_size_fft) for key in self.fft_keys}
            # for key in self.fft_keys:
            #     self.fft_dict[key].extend([0 for _ in range(window_size_fft)])

        # IMU data
        self.acc_keys = ['acc_x', 'acc_y', 'acc_z']
        self.magn_keys = ['magn_x', 'magn_y', 'magn_z']
        self.gyro_keys = ['gyro_x', 'gyro_y', 'gyro_z']
        self.imu_keys = self.acc_keys + self.magn_keys + self.gyro_keys
        self.imu_dict = {key: deque(maxlen=window_size_imu) for key in self.imu_keys}
        # for key in self.imu_keys:
        #     self.imu_dict[key].extend([0 for _ in range(window_size_imu)])

        # Ridisegno a 10 Hz, disaccoppiato dalla cadenza di arrivo dei dati.
        self.timer = QtCore.QTimer()
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_plot)
        self.timer.start()

        # Persistenza visiva dei classificatori: restano a zero, l'aggiornamento
        # e' commentato.
        self.jaw_clench_hold_timer = 0
        self.heog_left_hold_timer = 0
        self.heog_right_hold_timer = 0

        # CLI disattivato: calcolo commentato in update_predictions_visuals,
        # asse rimosso da ui_builder.initUI, cli_line senza artist.
        self.cli_data = deque()
        self.cli_data_plot = deque(maxlen=PLOT_WINDOW_SECONDS)
        self.cli_window = CLI_SMOOTHING_SECONDS
        self.cli_line = None
        
        # baseline
        self.baseline_ready = False
        self.baseline_start_ts = None
        self.baseline_ratios = {'alpha': [], 'beta': [], 'sigma': []}
        self.baseline_alpha = None
        self.baseline_beta = None
        self.baseline_sigma = None
        self.last_band_powers = None

        # Potenze assolute per banda, bufferizzate per il plot real-time
        self.band_data_plot = {b: deque(maxlen=PLOT_WINDOW_SECONDS) for b in brainwave_bands}
        self.band_lines = {}

        # Origine di t_rel, per le etichette dell'asse e i log. Il CSV registra
        # tempi assoluti.
        self.session_start_ts = None

        # CSV del CLI: disattivato insieme al CLI. Per riattivarlo, aprirlo qui
        # come bands_csv, sotto LOG_DIR.
        self.cli_csv_path = None
        self.cli_csv_file = None
        self.cli_csv_writer = None

        # Aperto al click su Start e chiuso allo Stop, cosi' ogni file
        # corrisponde a una sessione di misura.
        self.bands_csv_path = None
        self.bands_csv_file = None
        self.bands_csv_writer = None

        # Stato della registrazione controllato dai pulsanti Start/Stop
        self.recording_active = False
        self.recording_start_ts = None
        self.recording_rows = 0
        # Scarti per motivo: diagnostica locale, non inviata al backend.
        self.recording_rejected = Counter()
        self.recording_stop_ts = None
        self.session_id = None
        self.ntp_offset_s = None  # scostamento misurato dell'orologio di sistema

        # pending_events tiene tutti gli eventi della sessione nell'ordine di
        # scrittura sul CSV; upload_cursor segna quanti il backend ha
        # confermato, quindi pending_events[upload_cursor:] e' cio' che resta
        # da inviare. Gli eventi non vengono rimossi dopo l'invio.
        self.pending_events = []
        self.upload_cursor = 0
        # Un solo chunk in volo: con due POST concorrenti l'ordine di
        # completamento non e' garantito e il cursore diventerebbe ambiguo.
        self.upload_in_flight = False
        self.chunk_seq = 0  # progressivo, permette al backend di rilevare buchi

        # Campioni (wall_time, offset) sulla finestra scorrevole.
        self.clock_offset_samples = deque()
        # Ancora letta all'arrivo di un pacchetto: data le righe del CSV.
        self.last_packet_local_ts = None
        self.last_packet_eeg_ts = None
        self.last_sync_log_ts = 0.0
        self.offset_history = []  # (wall_time, offset_min) per il fit sulla deriva

        self.quality_ok = False
        # Il primo arrivo prova che lo stream di predizioni e' attivo ed e' una
        # condizione di sblocco di Start; il valore lo usa solo il CSV del CLI.
        self.last_fft_zscores = None

        self.initUI()

    def closeEvent(self, event):
        # Chiusura senza Stop: il file resterebbe aperto e l'ultimo buffer
        # andrebbe perso.
        if self.recording_active:
            self.stop_recording()
        if self.on_close:
            self.on_close()
        event.accept()

    # ---------------------------------------------------------------- #
    #  Controllo della registrazione (Start / Stop)                     #
    # ---------------------------------------------------------------- #

    def can_start_recording(self):
        """
        Impedenza sotto soglia e almeno un gruppo di z-score ricevuto, che
        prova che lo stream di predizioni e' attivo.
        """
        return (self.impedance_data <= self.IMPEDANCE_THRESHOLD
                and self.last_fft_zscores is not None
                and not self.recording_active)

    def refresh_recording_controls(self):
        """
        Allinea i pulsanti alle condizioni correnti. Invocato da handler che
        girano nel thread GUI: nessuna sincronizzazione necessaria.
        """
        self.start_button.setEnabled(self.can_start_recording())
        self.stop_button.setEnabled(self.recording_active)

    def start_recording(self):
        """
        Apre il CSV della sessione, abilita la scrittura delle potenze e
        registra la sessione sul backend.
        """
        if self.recording_active:
            return

        # Chiave di correlazione. Il plugin Moodle non la conosce: e' il
        # backend ad assegnarla ai suoi eventi.
        self.session_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs(LOG_DIR, exist_ok=True)
        self.bands_csv_path = os.path.join(LOG_DIR, f"bands_log_idun_{self.session_id}.csv")
        self.bands_csv_file = open(self.bands_csv_path, "w", newline="")
        self.bands_csv_writer = csv.writer(self.bands_csv_file, delimiter=';')
        self.bands_csv_writer.writerow([
            "timestamp_local", "timestamp_idun",
            "p_delta", "p_theta", "p_alpha", "p_sigma", "p_beta", "p_gamma",
        ])
        self.bands_csv_file.flush()

        self.recording_active = True
        self.recording_rows = 0
        self.recording_rejected = Counter()
        self.recording_stop_ts = None
        self.recording_start_ts = time.time()

        # La stessa istanza puo' registrare piu' sessioni: senza azzerare, il
        # cursore precedente darebbe per inviati i primi campioni di questa.
        self.pending_events = []
        self.upload_cursor = 0
        self.chunk_seq = 0

        self.recording_status.setText(f"Recording -> {self.bands_csv_path}")
        self.recording_status.setStyleSheet("font-size: 14px; color: #00AA00;")
        self.refresh_recording_controls()
        offset = self.get_clock_offset()
        offset_str = f"{offset:.3f}s" if offset is not None else "non disponibile"
        print(f"[REC] avvio registrazione su {self.bands_csv_path} "
              f"(offset clock EEG->macchina: {offset_str})", flush=True)

        # Da qui il backend conosce il session_id e puo' assegnarlo agli eventi
        # Moodle. Asincrona: un fallimento non interrompe la registrazione
        # locale, e l'attesa della query NTP non blocca la GUI.
        self.open_session_async(self.session_id, self.recording_start_ts)

    def stop_recording(self):
        """Chiude il CSV, conclude l'upload e riabilita Start."""
        if not self.recording_active:
            return

        self.recording_active = False
        self.recording_stop_ts = time.time()
        path = self.bands_csv_path
        rows = self.recording_rows

        if self.bands_csv_file is not None:
            self.bands_csv_file.flush()
            self.bands_csv_file.close()
        self.bands_csv_file = None
        self.bands_csv_writer = None

        self.recording_status.setText(f"Stopped - {rows} campioni in {path}")
        self.recording_status.setStyleSheet("font-size: 14px; color: #404040;")
        self.refresh_recording_controls()
        print(f"[REC] registrazione conclusa: {rows} campioni in {path}", flush=True)

        self.finalize_upload(path, self.session_id)


    def update_signals_visuals(self, signal, imu_data):
        """
        Accoda ai buffer un pacchetto di live insights.

        Args:
            signal (list): coppie (timestamp EEG, ch1).
            imu_data (list): un dizionario per campione, con 'timestamp' e le
                nove componenti IMU.
        """
        self.signal_data.extend(signal)

        if self.session_start_ts is None and self.signal_data:
            self.session_start_ts = self.signal_data[0][0]

        # Aggiorna la stima dell'offset di clock sull'istante di ricezione
        self.update_clock_offset()

        for sample in imu_data:
            ts = sample['timestamp']
            for key in self.imu_keys:
                self.imu_dict[key].append((ts, sample[key]))
    
    def update_impedance_visuals(self, impedance_value):
        """
        Mostra l'impedenza e rivaluta lo sblocco di Start.

        Args:
            impedance_value (float): Ohm, gia' mediata dal chiamante.
        """
        self.impedance_data = impedance_value
        self.impedance_value.setText(f"{self.impedance_data /1000:.0f} kOhm")
        color = "#00AA00" if impedance_value <= self.IMPEDANCE_THRESHOLD else "#FF0000"
        self.impedance_value.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {color};")
        self.refresh_recording_controls()
        #print(f"Impedance value received: {impedance_value} Ohm", flush=True)

    def update_device_connected_visuals(self, connected):
        """Aggiorna l'indicatore di connessione BLE."""
        self.device_connected = connected
        self.connection_status.setText("Connected" if connected else "Disconnected")
        if connected:
            self.disconnect_button.setIcon(QIcon("front_end/images/disconnect.png"))
            self.disconnect_button.setIconSize(QtCore.QSize(image_size, image_size))
            self.disconnect_button.clicked.connect(self.close)
    
    def update_predictions_visuals(self, quality_score, new_jaw_clench, new_heog_left, new_heog_right, fft_data):
        """
        Recepisce un evento di predizione dell'SDK.

        Ogni evento porta un solo tipo di predizione, quindi a ogni chiamata
        uno solo dei parametri e' valorizzato e gli altri valgono il default
        del chiamante. Il ramo del quality score innesca calcolo e
        registrazione delle potenze di banda.

        Args:
            quality_score (float): None se l'evento non e' di quel tipo.
            fft_data (tuple): (timestamp, z-score per banda); timestamp None e
                dizionario vuoto fuori dagli eventi FFT.
        """
        # Base dei tempi degli hold timer, oggi inutilizzata.
        current_time = QtCore.QTime.currentTime().msecsSinceStartOfDay()

        # Il primo arrivo di z-score sblocca Start.
        _, zscore_dict = fft_data
        if zscore_dict:
            first_zscores = self.last_fft_zscores is None
            self.last_fft_zscores = zscore_dict
            if first_zscores:
                self.refresh_recording_controls()
                if self.can_start_recording():
                    self.recording_status.setText("Pronto: premi Start per registrare")

        # Update detection hold timers
        # if new_jaw_clench:
        #     self.jaw_clench_detected = new_jaw_clench
        #     self.jaw_clench_hold_timer = current_time + hold_duration

        # if new_heog_left:
        #     self.heog_left_detected = new_heog_left
        #     self.heog_left_hold_timer = current_time + hold_duration

        # if new_heog_right:
        #     self.heog_right_detected = new_heog_right
        #     self.heog_right_hold_timer = current_time + hold_duration

        if quality_score is not None:
            self.quality_score.append(quality_score)
            self.quality_ok = quality_score > QUALITY_SCORE_THRESHOLD

            # Senza questa riga window_quality_ok riceve sempre una lista vuota
            # e non filtra nulla.
            if self.signal_data:
                self.quality_history.append((self.signal_data[-1][0], quality_score))

            if not self.quality_ok and self.signal_data:
                self.buffer_valid_from_ts = self.signal_data[-1][0]

            # Il tick di qualita' e' anche la cadenza di elaborazione. Il gating
            # e' dentro log_band_powers.
            if self.signal_data:
                self.log_band_powers(self.signal_data[-1][0])

            # CLI scollegato: il calcolo resta disponibile, per riattivarlo
            # scommentare il blocco seguente.
            # if self.quality_ok and self.signal_data:
            #     eeg_ts = self.signal_data[-1][0]
            #     if not self.baseline_ready:
            #         if self.last_fft_zscores is not None:
            #             # Attende che l'SDK inizi a restituire z-score prima di iniziare
            #             # ad accumulare la baseline, per non calcolarla su una finestra
            #             # in cui anche il modello interno dell'SDK non e' ancora "pronto"
            #             self.compute_baseline(eeg_ts)
            #         elif DEBUG_CLI:
            #             print(f"[CLI-DEBUG] {eeg_ts:.2f}: in attesa del primo z-score SDK prima di avviare la baseline", flush=True)
            #     else:
            #         cli_value = self.compute_cli_realtime(eeg_ts)
            #         if cli_value is not None:
            #             self.cli_data_plot.append((eeg_ts, cli_value))
            # elif DEBUG_CLI and not self.quality_ok:
            #     print(f"[CLI-DEBUG] quality={quality_score:.1f} sotto soglia -> skip", flush=True)
                

        # Gli z-score restano nel grafico ma non entrano in nessun calcolo. Il
        # filtro qui e' sul tick corrente, non sull'intera finestra Welch.
        timestamp, fft_dict = fft_data
        if timestamp is not None and fft_dict != {}:
            if self.quality_ok:
                for key in self.fft_keys:
                    if fft_dict[key] is not None:
                        self.fft_dict[key].append((timestamp, fft_dict[key]))

    def update_plot(self):
        """Ridisegna i grafici. Invocata dal QTimer a 10 Hz."""
        # Update classifier flags
        # current_time = QtCore.QTime.currentTime().msecsSinceStartOfDay()
        # self.jaw_clench_detected = current_time < self.jaw_clench_hold_timer
        # self.heog_left_detected = current_time < self.heog_left_hold_timer
        # self.heog_right_detected = current_time < self.heog_right_hold_timer

        if self.signal_data:
            timestamps, eeg_values = zip(*self.signal_data)
            self.line_signal.set_xdata(timestamps)
            self.line_signal.set_ydata(eeg_values)
            # Senza riallineare l'asse la traccia scorre fuori dall'area
            # visibile.
            self._update_signal_xticks(timestamps)

        if self.plot_FFT:
            for key in self.fft_keys:
                if self.fft_dict[key]:
                    ts, vals = zip(*self.fft_dict[key])
                    self.fft_lines[key].set_xdata(ts)
                    self.fft_lines[key].set_ydata(vals)

        # Nessun autoscale: ax_power ha limiti fissi (vedi initUI).
        for key in brainwave_bands:
            if self.band_data_plot[key]:
                ts, vals = zip(*self.band_data_plot[key])
                self.band_lines[key].set_xdata(ts)
                self.band_lines[key].set_ydata(vals)

        # ax_power e' un twinx di ax_fft: asse x condiviso, si imposta una
        # volta sola su un intervallo comune. L'inizio e' ancorato al dato piu'
        # vecchio presente e non a un'ampiezza fissa, perche'
        # PLOT_WINDOW_SECONDS e' il maxlen dei deque in campioni: con una
        # finestra fissa i primi minuti mostrerebbero l'asse gia' pieno fino a
        # prima dell'inizio della sessione.
        earliest, latest = [], []
        if self.band_data_plot['Delta']:
            earliest.append(self.band_data_plot['Delta'][0][0])
            latest.append(self.band_data_plot['Delta'][-1][0])
        if self.plot_FFT and self.fft_dict[self.fft_keys[0]]:
            earliest.append(self.fft_dict[self.fft_keys[0]][0][0])
            latest.append(self.fft_dict[self.fft_keys[0]][-1][0])
        if latest:
            t_end = max(latest)
            t_start = max(t_end - PLOT_WINDOW_SECONDS, min(earliest))
            self._update_time_axis(self.ax_fft, t_start, t_end)


        # Asse x per indice, non per tempo: mostra gli ultimi N tick.
        if len(self.quality_score) > 1:
            n = len(self.quality_score)
            self.line_quality.set_xdata(range(n))
            self.line_quality.set_ydata(self.quality_score)
            self.ax_quality.set_xlim(0, n-1)

        self.canvas.draw()

        # Update IMU plots
        # for key in self.acc_keys:
        #     if self.imu_dict[key]:
        #         ts, vals = zip(*self.imu_dict[key])
        #         self.acc_lines[key].set_xdata(ts)
        #         self.acc_lines[key].set_ydata(vals)
        # Update acc x ticks once using the last key's timestamps
        # if self.imu_dict[self.acc_keys[0]]:
        #     ts, _ = zip(*self.imu_dict[self.acc_keys[0]])
        #     self._update_xticks(self.ax_acc, ts)
        # for key in self.magn_keys:
        #     if self.imu_dict[key]:
        #         ts, vals = zip(*self.imu_dict[key])
        #         self.magn_lines[key].set_xdata(ts)
        #         self.magn_lines[key].set_ydata(vals)
        # if self.imu_dict[self.magn_keys[0]]:
        #     ts, _ = zip(*self.imu_dict[self.magn_keys[0]])
        #     self._update_xticks(self.ax_magn, ts)
        # for key in self.gyro_keys:
        #     if self.imu_dict[key]:
        #         ts, vals = zip(*self.imu_dict[key])
        #         self.gyro_lines[key].set_xdata(ts)
        #         self.gyro_lines[key].set_ydata(vals)
        # if self.imu_dict[self.gyro_keys[0]]:
        #     ts, _ = zip(*self.imu_dict[self.gyro_keys[0]])
        #     self._update_xticks(self.ax_gyro, ts)
        self.canvas_fft.draw()

        # Jaw clench image
        # if self.jaw_clench_detected:
        #     pixmap = QPixmap("front_end/images/jaw_clench.png")
        # else:
        #     pixmap = QPixmap("front_end/images/circle_grey.png")
        # self.quality_value.setPixmap(pixmap.scaled(
        #     image_size, image_size,
        #     QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        #     QtCore.Qt.TransformationMode.SmoothTransformation
        # ))

        # Left HEOG image
        # if self.heog_left_detected:
        #     pixmap = QPixmap("front_end/images/HEOG_left.png")
        # else:
        #     pixmap = QPixmap("front_end/images/left_grey.png")
        # self.impedance_value.setPixmap(pixmap.scaled(
        #     image_size, image_size,
        #     QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        #     QtCore.Qt.TransformationMode.SmoothTransformation
        # ))

        # Right HEOG image
        # if self.heog_right_detected:
        #     pixmap = QPixmap("front_end/images/HEOG_right.png")
        # else:
        #     pixmap = QPixmap("front_end/images/right_grey.png")
        # self.disconnect_button.setPixmap(pixmap.scaled(
        #     image_size, image_size,
        #     QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        #     QtCore.Qt.TransformationMode.SmoothTransformation
        # ))