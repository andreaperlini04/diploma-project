"""
Allineamento tra il clock dei timestamp EEG e l'orologio della macchina.
"""

import time

import numpy as np

from .config import (
    DEBUG_SYNC,
    FS,
    SYNC_DRIFT_MIN_POINTS,
    SYNC_LOG_INTERVAL_SECONDS,
    SYNC_OFFSET_WINDOW_SECONDS,
)


class ClockSyncMixin:
    """
    Stima dell'offset e della deriva del clock. Mixin: opera sugli attributi
    dell'istanza di EEGVisualizer.
    """

    def update_clock_offset(self):
        """
        Registra un campione di offset all'arrivo di ogni pacchetto EEG.

        La misura va presa qui e non al tick di quality_score: quest'ultimo
        arriva dal cloud IDUN e include il round-trip di rete.
        """
        if not self.signal_data:
            return

        now = time.time()
        ts_eeg = self.signal_data[-1][0]

        # Ancora per la datazione dei campioni registrati (vedi
        # packet_local_time). I due valori vanno assegnati sempre insieme,
        # altrimenti l'estrapolazione parte da una coppia incoerente.
        self.last_packet_local_ts = now
        self.last_packet_eeg_ts = ts_eeg

        self.clock_offset_samples.append((now, now - ts_eeg))

        cutoff = now - SYNC_OFFSET_WINDOW_SECONDS
        while self.clock_offset_samples and self.clock_offset_samples[0][0] < cutoff:
            self.clock_offset_samples.popleft()

        if DEBUG_SYNC and now - self.last_sync_log_ts >= SYNC_LOG_INTERVAL_SECONDS:
            self.last_sync_log_ts = now
            offsets = [o for _, o in self.clock_offset_samples]
            offset_min = min(offsets)
            self.offset_history.append((now, offset_min))

            drift_str = ""
            drift = self.estimate_drift()
            if drift is not None:
                drift_str = (f" | deriva {drift['ppm']:+.0f} ppm su {drift['span_s']:.0f}s "
                             f"-> fs_fisica ~{drift['fs_implied']:.3f} Hz, "
                             f"{drift['error_15min_s']:+.2f}s su 15 min")

            print(f"[SYNC] offset={offset_min:.3f}s "
                  f"(jitter {max(offsets) - offset_min:.3f}s su {len(offsets)} campioni)"
                  + drift_str, flush=True)

    def estimate_drift(self):
        """
        Fit lineare dell'offset sull'intera sessione.

        Un offset decrescente significa che la griglia sintetica dell'SDK
        avanza piu' in fretta del tempo reale, cioe' fs fisica > FS. Se la
        pendenza tende a zero al crescere della sessione, la discesa iniziale
        era solo la convergenza del filtro a minimo.

        Returns:
            dict or None: ppm, fs_implied, span_s, error_15min_s, n_points.
            None sotto SYNC_DRIFT_MIN_POINTS punti.
        """
        if len(self.offset_history) < SYNC_DRIFT_MIN_POINTS:
            return None

        t_hist = np.array([t for t, _ in self.offset_history])
        o_hist = np.array([o for _, o in self.offset_history])
        slope = np.polyfit(t_hist - t_hist[0], o_hist, 1)[0]
        ppm = -slope * 1e6

        return {
            'ppm': float(ppm),
            'fs_implied': float(FS * (1.0 + ppm / 1e6)),
            'span_s': float(t_hist[-1] - t_hist[0]),
            'error_15min_s': float(-slope * 900),
            'n_points': len(self.offset_history),
        }

    def get_clock_offset(self):
        """Offset stimato, o None se non ci sono ancora campioni."""
        if not self.clock_offset_samples:
            return None
        return min(o for _, o in self.clock_offset_samples)

    def packet_local_time(self, eeg_timestamp):
        """
        Orologio locale da registrare accanto a un timestamp EEG.

        Non e' una conversione: e' la lettura di time.time() presa all'arrivo
        del pacchetto. Leggerla qui invece che al momento della scrittura
        della riga toglie dal dato l'attesa del tick di qualita' (fino a circa
        un secondo) e il tempo di calcolo di Welch, ritardi che dipendono
        dalla macchina e non dall'acquisizione.

        Oggi eeg_timestamp coincide sempre con l'ancora, quindi il termine di
        estrapolazione e' zero; la forma generale resta corretta se un domani
        la finestra venisse datata su un altro campione.
        """
        if self.last_packet_local_ts is None:
            return time.time()
        return self.last_packet_local_ts + (eeg_timestamp - self.last_packet_eeg_ts)

    def to_local_time(self, eeg_timestamp):
        """
        Converte un timestamp EEG applicando l'offset stimato.

        Non usata dal percorso di registrazione, che scrive le due basi
        temporali grezze: la conversione resta per l'analisi, dove puo' essere
        rifatta sull'intera sessione e con la deriva.
        """
        offset = self.get_clock_offset()
        if offset is None:
            return time.time()
        return eeg_timestamp + offset
