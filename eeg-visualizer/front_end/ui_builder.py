"""
Costruzione della finestra PyQt6 e degli assi matplotlib. Solo layout: i
metodi di aggiornamento dei dati restano in EEGVisualizer.
"""

from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtGui import QIcon

from .config import (
    POWER_YLIM_MAX,
    POWER_YLIM_MIN,
    PLOT_WINDOW_SECONDS,
    band_colors,
    brainwave_bands,
    image_size,
    window_size_fft,
)


class UIBuilderMixin:
    """
    Costruzione dell'interfaccia e formattazione degli assi. Mixin: assegna
    sull'istanza di EEGVisualizer i widget e gli artist matplotlib usati dai
    metodi di aggiornamento.
    """

    def _update_signal_xticks(self, timestamps):
        """
        Riallinea l'asse temporale del grafico EEG. Le etichette sono ore
        assolute, a differenza degli altri due assi.
        """
        if len(timestamps) < 2 or  timestamps[0] == timestamps[-1]:
            return
        # Sotto il secondo di dati i tick sarebbero tutti sulla stessa etichetta.
        if timestamps[-1] - timestamps[0] < 1.0:
            return
        self.ax_signal.set_xlim(timestamps[0], timestamps[-1])
        step = max(1, len(timestamps) // 10)
        tick_indices = timestamps[::step]
        self.ax_signal.set_xticks(tick_indices)
        self.ax_signal.set_xticklabels(
            [datetime.fromtimestamp(t).strftime('%H:%M:%S') if t != 0 else '' for t in tick_indices],
            rotation=45, fontsize=7
        )

    def _update_time_axis(self, ax, t_start, t_end, n_ticks=8):
        """
        Asse temporale condiviso da z-score e potenze, etichettato in secondi
        dall'inizio sessione. Va passato ax_fft: ax_power e' un suo twinx.
        """
        if t_end <= t_start:
            return
        ax.set_xlim(t_start, t_end)
        ticks = np.linspace(t_start, t_end, n_ticks)
        ax.set_xticks(ticks)
        ax.set_xticklabels(
            [f"{self.t_rel(t):.0f}s" for t in ticks],
            rotation=45, fontsize=7
        )

    def initUI(self):
        """
        Due colonne di grafici in alto, riga di controllo della registrazione
        in basso.
        """
        self.setStyleSheet("background-color: white; color: black;")

        main_layout = QtWidgets.QVBoxLayout()

        top_layout = QtWidgets.QHBoxLayout()
        left_layout = QtWidgets.QVBoxLayout()
        right_layout = QtWidgets.QVBoxLayout()

        title_style_sections = """
            QLabel {
                font-size: 20px;
                font-weight: bold;
                color: #404040;
            }
        """

        #---------- LEFT: EEG ----------------------------------------------------------------
        title_signal = QtWidgets.QLabel("EEG Data")
        title_signal.setStyleSheet(title_style_sections)
        title_signal.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(title_signal)

        plot_layout = QtWidgets.QVBoxLayout()
        #if self.plot_FFT:
        #    self.figure, (self.ax_signal, self.ax_quality, self.ax_fft) = plt.subplots(3, 1, figsize=(12, 12))
        #else:
        self.figure, (self.ax_signal, self.ax_quality) = plt.subplots(2, 1, figsize=(12, 8))
        
        self.canvas = FigureCanvas(self.figure)
        self.figure.tight_layout(pad=3.0, h_pad=10.0)

        # EEG signal
        self.ax_signal.set_title("Filtered EEG Signal (µV)")
        if self.signal_data:
            timestamps, eeg_values = zip(*self.signal_data)
            # Timestamp come dati x, come update_plot: altrimenti il primo
            # aggiornamento cambierebbe unita' all'asse.
            self.line_signal, = self.ax_signal.plot(timestamps, eeg_values, color='#14786e', linewidth=1)
            self._update_signal_xticks(timestamps)
        else:
            self.line_signal, = self.ax_signal.plot([], [], color='#14786e', linewidth=1)
        self.ax_signal.set_ylim(-100, 100)
        # Quality score
        self.ax_quality.set_title("Quality Score (%)")
        self.line_quality, = self.ax_quality.plot([], [], color='black', linewidth=1)
        self.ax_quality.set_xlim(0, window_size_fft - 1)  # set initial x range
        self.ax_quality.set_ylim(-2, 102)
        self.ax_quality.set_xticks([])
        
        # FFT
        # if self.plot_FFT:
        #     self.ax_fft.set_title("FFT (z-scores)")
        #     self.fft_lines = {}
        #     for key in self.fft_keys:
        #         self.fft_lines[key], = self.ax_fft.plot(
        #             [], [],
        #             label=f"{key} {brainwave_bands[key]}",
        #             color=band_colors[key],
        #             linewidth=1.5
        #         )
        #     self.ax_fft.set_ylim(-10, 10)
        #     self.ax_fft.legend(loc='upper left')

        plot_layout.addWidget(self.canvas)
        left_layout.addLayout(plot_layout)
        top_layout.addLayout(left_layout)

        #---------- RIGHT: FFT ----------------------------------------------------------------
        title_fft = QtWidgets.QLabel("FFT Data")
        title_fft.setStyleSheet(title_style_sections)
        title_fft.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(title_fft)
        self.figure_fft, self.ax_fft = plt.subplots(figsize=(12, 8))
        self.canvas_fft = FigureCanvas(self.figure_fft)
        self.figure_fft.tight_layout(pad=3.0, h_pad=10.0)
        self.ax_fft.set_title("FFT (z-scores)")
        self.fft_lines = {}
        for key in self.fft_keys:
            self.fft_lines[key], = self.ax_fft.plot(
                [], [],
                label=f"{key} {brainwave_bands[key]}",
                color=band_colors[key],
                linewidth=1.5
            )
        self.ax_fft.set_ylim(-10, 10)
        # Placeholder fino al primo dato reale: senza, l'asse resta nel range
        # vuoto di default di matplotlib fino al primo tick di qualita'.
        self.ax_fft.set_xlim(0, PLOT_WINDOW_SECONDS)
        self.ax_fft.legend(loc='upper left')

        #---------- second y-axis: potenze assolute (Welch) --------------------------------------
        # Scala logaritmica: su scala lineare Beta e Gamma sarebbero appiattite
        # dalle bande basse, superiori di ordini di grandezza.
        #
        # L'asse CLI (terzo y-axis) e' stato rimosso perche' cli_data_plot
        # resta sempre vuoto. Per riattivarlo, ricostruire ax_cli prima di
        # questo blocco, cosi' l'offset di ax_power resta corretto.
        self.ax_power = self.ax_fft.twinx()
        self.ax_power.set_ylabel("Potenza assoluta (µV²)")
        self.ax_power.set_yscale('log')
        # Limiti fissi (vedi config.py).
        self.ax_power.set_ylim(POWER_YLIM_MIN, POWER_YLIM_MAX)
        for key in self.fft_keys:
            # tratteggio per distinguerle dagli z-score SDK, che usano gli stessi colori
            self.band_lines[key], = self.ax_power.plot(
                [], [], color=band_colors[key], linewidth=1.5,
                linestyle='--', label=f"{key} (Welch)"
            )
        self.ax_power.legend(loc='lower right', fontsize=7)
        self.ax_fft.legend(loc='upper left', fontsize=7)

        # title_imu = QtWidgets.QLabel("IMU Data")
        # title_imu.setStyleSheet(title_style_sections)
        # title_imu.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        # right_layout.addWidget(title_imu)

        # self.figure_imu, (self.ax_acc, self.ax_magn, self.ax_gyro) = plt.subplots(3, 1, figsize=(12, 12))
        # self.canvas_imu = FigureCanvas(self.figure_imu)
        # self.figure_imu.tight_layout(pad=3.0, h_pad=10.0)

        # # Accelerometer
        # self.ax_acc.set_title("Accelerometer Data (m/s²)")
        # self.acc_lines = {}
        # for key in self.acc_keys:
        #     axis = key.split('_')[1]
        #     self.acc_lines[key], = self.ax_acc.plot([], [], label=axis, linewidth=1, color=imu_colors[axis])
        # self.ax_acc.set_ylim(-20, 15)
        # self.ax_acc.legend(loc='upper left')

        # # Magnetometer
        # self.ax_magn.set_title("Magnetometer Data (µT)")
        # self.magn_lines = {}
        # for key in self.magn_keys:
        #     axis = key.split('_')[1]
        #     self.magn_lines[key], = self.ax_magn.plot([], [], label=axis, linewidth=1, color=imu_colors[axis])
        # self.ax_magn.set_ylim(-2, 2)
        # self.ax_magn.legend(loc='upper left')

        # # Gyroscope
        # self.ax_gyro.set_title("Gyroscope Data (°/s)")
        # self.gyro_lines = {}
        # for key in self.gyro_keys:
        #     axis = key.split('_')[1]
        #     self.gyro_lines[key], = self.ax_gyro.plot([], [], label=axis, linewidth=1, color=imu_colors[axis])
        # self.ax_gyro.set_ylim(-7, 7)
        # self.ax_gyro.legend(loc='upper left')

        #right_layout.addWidget(self.canvas_imu)
        right_layout.addWidget(self.canvas_fft)
        top_layout.addLayout(right_layout)
        
        main_layout.addLayout(top_layout)
        
        #------------ Classifiers layout 
        classifier_layout = QtWidgets.QVBoxLayout()
        management_layout = QtWidgets.QGridLayout()

        # Tre colonne di uguale larghezza, non pesate sul contenuto: cosi'
        # risultano simmetriche come blocchi, non solo internamente.
        management_layout.setColumnStretch(0, 1)
        management_layout.setColumnStretch(1, 1)
        management_layout.setColumnStretch(2, 1)

        title_style = """
            QLabel {
                font-size: 20px;
                font-weight: bold;
                color: #404040;
            }
        """

        impedance_style = """
            QLabel {
                font-size: 20px;
                font-weight: bold;
                color: #FF0000;
            }
        """

        title_impedance = QtWidgets.QLabel("Impedance")
        title_status = QtWidgets.QLabel("Status")
        title_connection = QtWidgets.QLabel("Connection")
        title_impedance.setStyleSheet(title_style)
        title_status.setStyleSheet(title_style)
        title_connection.setStyleSheet(title_style)
        
        management_layout.addWidget(title_impedance, 0, 0, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        management_layout.addWidget(title_connection, 0, 1, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        management_layout.addWidget(title_status, 0, 2, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        
        self.impedance_value = QtWidgets.QLabel()
        self.impedance_value.setStyleSheet(impedance_style)
        self.connection_status = QtWidgets.QLabel("Disconnected")
        self.connection_status.setStyleSheet("font-size: 20px; font-weight: bold")
        self.disconnect_button = QtWidgets.QPushButton()
        
        #resting_jaw_clench_image = QPixmap("front_end/images/circle_grey.png").scaled(image_size, image_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
        #resting_heog_left_image = QPixmap("front_end/images/left_grey.png").scaled(image_size, image_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
        #disconnect_image = QPixmap("front_end/images/disconnect.png").scaled(image_size, image_size, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)

        #self.quality_value.setPixmap(resting_jaw_clench_image)
        #self.impedance_value.setPixmap(resting_heog_left_image)
        self.impedance_value.setText(f"{self.impedance_data /1000:.0f} Ohm")
        self.disconnect_button.setIcon(QIcon("front_end/images/no-connection.png"))
        self.disconnect_button.setIconSize(QtCore.QSize(image_size, image_size))
        #self.disconnect_button.clicked.connect(self.close)
        
        # ---- Pulsanti di registrazione, sotto il valore di impedenza ----
        button_style = """
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                padding: 6px 18px;
            }
            QPushButton:disabled {
                color: #A0A0A0;
            }
        """

        self.start_button = QtWidgets.QPushButton("Start")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.start_button.setStyleSheet(button_style)
        self.stop_button.setStyleSheet(button_style)
        # Entrambi bloccati fino a impedenza sotto soglia + primo z-score ricevuto
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)

        recording_layout = QtWidgets.QHBoxLayout()
        recording_layout.addWidget(self.start_button)
        recording_layout.addWidget(self.stop_button)
        # Nessuno stretch: la riga e' centrata come blocco nella cella e
        # dimensionata alla larghezza minima dei due pulsanti.

        self.recording_status = QtWidgets.QLabel("In attesa di impedenza e z-score...")
        self.recording_status.setStyleSheet("font-size: 14px; color: #404040;")

        # Centrato come il titolo sopra: a sinistra il contenuto resterebbe
        # incollato al bordo di questa colonna, la piu' larga delle tre.
        management_layout.addWidget(self.impedance_value, 1, 0, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        management_layout.addLayout(recording_layout, 2, 0, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        management_layout.addWidget(self.recording_status, 3, 0, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        #management_layout.addWidget(self.quality_value, 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        management_layout.addWidget(self.connection_status, 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        management_layout.addWidget(self.disconnect_button, 1, 2, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        classifier_layout.addLayout(management_layout)
        main_layout.addLayout(classifier_layout)
        
        self.setLayout(main_layout)