"""
Elaborazione del segnale EEG: potenze di banda via Welch, gating e logging
su CSV. Contiene anche il calcolo del Cognitive Load Index, oggi scollegato
dal flusso ma conservato per un'eventuale riattivazione.
"""

from datetime import datetime

import numpy as np
from scipy.signal import welch

from .config import (
    BASELINE_DURATION_SECONDS,
    DEBUG_BANDS,
    DEBUG_CLI,
    FS,
    QUALITY_SCORE_THRESHOLD,
    WELCH_MAX_GAP_SECONDS,
    WELCH_NOVERLAP,
    WELCH_NOVERLAP_SECONDS,
    WELCH_NPERSEG,
    WELCH_NPERSEG_SECONDS,
    WELCH_WINDOW_SECONDS,
    brainwave_bands,
)


class SignalProcessingMixin:
    """
    Calcolo spettrale e scrittura del CSV delle potenze. Mixin: opera sugli
    attributi dell'istanza di EEGVisualizer.
    """

    def compute_band_powers(self, eeg_buffer, fs=FS, nperseg=WELCH_NPERSEG,
                           noverlap=WELCH_NOVERLAP, scaling='density'):
        """
        Potenza assoluta per banda, integrando la densita' spettrale stimata
        con Welch. I default in campioni valgono a FS nominale; il percorso di
        registrazione passa sempre valori riscalati sulla fs reale.

        Returns:
            dict or None: potenza per banda, None se la finestra e' piu'
            corta di un segmento.
        """
        if len(eeg_buffer) < nperseg:
            return None

        # average='median': un segmento con artefatto diventa un outlier che
        # la mediana ignora, invece di alterare la stima come farebbe la media.
        freqs, psd = welch(eeg_buffer, fs=fs, nperseg=nperseg, noverlap=noverlap,
                           scaling=scaling, average='median')

        df = freqs[1] - freqs[0]

        band_powers = {}
        for band, (f_low, f_high) in brainwave_bands.items():
            mask = (freqs >= f_low) & (freqs < f_high)
            # Somma rettangolare: ogni bin e' la potenza di un intervallo
            # largo df divisa per df, quindi contribuisce con psd[k]*df.
            # np.trapezoid tratterebbe i bin come campioni puntuali e
            # dimezzerebbe quelli di bordo, sottostimando di (n-1)/n.
            band_powers[band] = psd[mask].sum() * df

        return band_powers

    def t_rel(self, timestamp):
        """Secondi trascorsi dal primo campione; 0.0 se l'origine non e' nota."""
        if self.session_start_ts is None:
            return 0.0
        return timestamp - self.session_start_ts

    def get_time_window(self, duration_s):
        """
        Campioni degli ultimi duration_s secondi REALI, selezionati per
        timestamp.

        Selezionare per indice assumerebbe che il dispositivo campioni
        esattamente a FS: se la fs reale devia, N campioni coprono una durata
        diversa da duration_s.
        """
        if not self.signal_data:
            return []
        data = list(self.signal_data)
        cutoff = data[-1][0] - duration_s
        return [sample for sample in data if sample[0] >= cutoff]

    def get_eeg_values(self, n_samples=None):
        """Ampiezze dal buffer, senza timestamp. n_samples assente: tutto."""
        if not self.signal_data:
            return np.array([])
        data = list(self.signal_data)
        if n_samples:
            data = data[-n_samples:]
        _, values = zip(*data)
        return np.array(values)

    def window_quality_ok(self, t_start, t_end):
        """
        True se nessun tick di qualita' caduto in [t_start, t_end] e' sotto
        soglia: basta un tratto scadente in mezzo per scartare l'intera
        finestra, anche se il tick piu' recente e' buono.

        Estremi inclusivi, soglia esclusiva. Senza tick nell'intervallo il
        risultato e' permissivo.
        """
        ticks = [q for ts, q in self.quality_history if t_start <= ts <= t_end]
        if not ticks:
            return True
        return min(ticks) > QUALITY_SCORE_THRESHOLD

    def compute_real_fs(self, timestamps):
        """
        Frequenza di campionamento effettiva della finestra, dall'intervallo
        medio fra timestamp. Ricade su FS se la finestra e' degenere.
        """
        diffs = np.diff(timestamps)
        mean_diff = np.mean(diffs)
        if mean_diff <= 0:
            return FS
        return 1.0 / mean_diff

    def window_is_continuous(self, timestamps, fs=FS,
                            max_gap_seconds=WELCH_MAX_GAP_SECONDS):
        """
        Confronta la durata reale della finestra con quella attesa dato il
        numero di campioni.

        fs deve essere la frequenza NOMINALE: con quella stimata dai
        timestamp stessi le due durate coinciderebbero per costruzione e il
        controllo sarebbe cieco anche a un buco evidente.

        Returns:
            bool: False anche sotto i due campioni, dove non esiste un
            intervallo da confrontare.
        """
        if len(timestamps) < 2:
            return False
        expected = (len(timestamps) - 1) / fs
        return abs((timestamps[-1] - timestamps[0]) - expected) <= max_gap_seconds

    def compute_band_ratios(self, timestamp):
        """
        I tre rapporti su cui si fonda il CLI: Alpha, Beta e Sigma relative,
        ciascuna divisa per Delta relativa.

        La potenza totale che normalizza esclude Sigma, che si sovrappone a
        Beta e verrebbe contata due volte.

        Returns:
            dict or None: chiavi 'alpha', 'beta', 'sigma'. None se la
            finestra non e' utilizzabile o il denominatore si annulla.
        """
        window_data = self.get_time_window(WELCH_WINDOW_SECONDS)
        if not window_data:
            return None
        timestamps, values = zip(*window_data)

        if not self.window_quality_ok(timestamps[0], timestamps[-1]):
            if DEBUG_CLI:
                print(f"[CLI-DEBUG] {timestamp:.2f}: finestra Welch contiene un tick di qualita' sotto soglia -> skip", flush=True)
            return None

        real_fs = self.compute_real_fs(timestamps)
        nperseg_real = max(2, round(WELCH_NPERSEG_SECONDS * real_fs))
        noverlap_real = min(nperseg_real - 1, round(WELCH_NOVERLAP_SECONDS * real_fs))
        band_powers = self.compute_band_powers(
            np.array(values), fs=real_fs,
            nperseg=nperseg_real, noverlap=noverlap_real)

        if band_powers is None:
            if DEBUG_CLI:
                print(f"[CLI-DEBUG] {timestamp:.2f}: buffer troppo corto per Welch -> skip", flush=True)
            return None

        # Riportate dal logging CSV del CLI accanto ai rapporti normalizzati.
        self.last_band_powers = band_powers

        total_power = (band_powers['Delta'] + band_powers['Theta'] + band_powers['Alpha'] + band_powers['Beta'] + band_powers['Gamma'])

        if total_power <= 0:
            if DEBUG_CLI:
                print(f"[CLI-DEBUG] {timestamp:.2f}: total_power={total_power} -> skip", flush=True)
            return None

        rel_delta = band_powers['Delta'] / total_power
        rel_alpha = band_powers['Alpha'] / total_power
        rel_beta  = band_powers['Beta']  / total_power
        rel_sigma = band_powers['Sigma'] / total_power

        if rel_delta == 0:
            return None

        return {
            'alpha': rel_alpha / rel_delta,
            'beta':  rel_beta  / rel_delta,
            'sigma': rel_sigma / rel_delta,
        }

    def compute_baseline(self, timestamp):
        """
        Accumula i rapporti di banda durante il riposo iniziale e, trascorsi
        BASELINE_DURATION_SECONDS, ne fissa la media come baseline. La durata
        e' misurata sul clock EEG.

        Returns:
            bool: True se la baseline e' pronta.
        """
        if self.baseline_ready:
            return True

        ratios = self.compute_band_ratios(timestamp)
        if ratios is None:
            return False

        if self.baseline_start_ts is None:
            self.baseline_start_ts = timestamp
            print(f"Inizio baseline: raccolta dati per {BASELINE_DURATION_SECONDS}s...", flush=True)

        self.baseline_ratios['alpha'].append(ratios['alpha'])
        self.baseline_ratios['beta'].append(ratios['beta'])
        self.baseline_ratios['sigma'].append(ratios['sigma'])

        elapsed = timestamp - self.baseline_start_ts
        if elapsed >= BASELINE_DURATION_SECONDS:
            self.baseline_alpha = np.mean(self.baseline_ratios['alpha'])
            self.baseline_beta = np.mean(self.baseline_ratios['beta'])
            self.baseline_sigma = np.mean(self.baseline_ratios['sigma'])
            self.baseline_ready = True
            print(f"Baseline pronta: alpha={self.baseline_alpha:.3f}, "
                f"beta={self.baseline_beta:.3f}, sigma={self.baseline_sigma:.3f}", flush=True)
            return True

        print(f"Baseline: {BASELINE_DURATION_SECONDS - elapsed:.0f}s rimanenti "
                    f"({len(self.baseline_ratios['alpha'])} campioni)", flush=True)
        return False

    def compute_cli_realtime(self, timestamp):
        """
        Cognitive Load Index: i tre rapporti normalizzati sulla baseline,
        mediati fra loro e lisciati su cli_window secondi. Un valore pari a 1
        corrisponde al carico della baseline. Scrive anche la riga sul CSV
        del CLI, se aperto.

        Returns:
            float or None: None se la baseline non e' pronta o la finestra
            non e' utilizzabile.
        """

        if not self.baseline_ready:
            return None

        ratios = self.compute_band_ratios(timestamp)
        if ratios is None:
            return None


        norm_alpha = ratios['alpha'] / self.baseline_alpha
        norm_beta = ratios['beta'] / self.baseline_beta
        norm_sigma = ratios['sigma'] / self.baseline_sigma

        cli_raw = (norm_alpha + norm_beta + norm_sigma) / 3
        self.cli_data.append((timestamp, cli_raw))

        current_quality = self.quality_score[-1] if self.quality_score else float('nan')

        if DEBUG_CLI:
            print(f"[CLI-DEBUG] {timestamp:.2f}: norm_alpha={norm_alpha:.3f}, "
                  f"norm_beta={norm_beta:.3f}, norm_sigma={norm_sigma:.3f}, "
                  f"cli_raw={cli_raw:.3f}, quality={current_quality:.1f}", flush=True)

        cutoff = timestamp - self.cli_window
        while self.cli_data and self.cli_data[0][0] < cutoff:
            self.cli_data.popleft()
        recent = [v for _, v in self.cli_data]

        if not recent:
            return None

        cli_smoothed = np.mean(recent)

        bp = self.last_band_powers
        z = self.last_fft_zscores or {}

        def zval(key):
            v = z.get(key)
            return f"{v:.4f}" if v is not None else ""

        if self.cli_csv_writer is None:
            # CSV del CLI non aperto: salta il logging.
            return cli_smoothed

        self.cli_csv_writer.writerow([
            f"{self.t_rel(timestamp):.2f}",
            datetime.now().isoformat(),
            f"{current_quality:.1f}",
            f"{cli_raw:.4f}",
            f"{cli_smoothed:.4f}",
            f"{bp['Delta']:.6g}",
            f"{bp['Theta']:.6g}",
            f"{bp['Alpha']:.6g}",
            f"{bp['Sigma']:.6g}",
            f"{bp['Beta']:.6g}",
            f"{bp['Gamma']:.6g}",
            zval('Delta'), zval('Theta'), zval('Alpha'),
            zval('Sigma'), zval('Beta'), zval('Gamma'),
        ])
        self.cli_csv_file.flush()

        if DEBUG_CLI:
            print(f"[CLI-DEBUG] {timestamp:.2f}: cli_smoothed={cli_smoothed:.3f} (su {len(recent)} campioni)", flush=True)

        return cli_smoothed

    def log_band_powers(self, timestamp):
        """
        Calcola le potenze sulla finestra corrente e le registra su CSV.

        Scrive solo se la registrazione e' attiva e la finestra e'
        utilizzabile: il CSV contiene quindi solo campioni affidabili, e i
        tratti scartati si riconoscono dalla distanza fra timestamp
        consecutivi.
        """
        quality = self.quality_score[-1] if self.quality_score else float('nan')
        window_data = self.get_time_window(WELCH_WINDOW_SECONDS)

        valid = 1
        reason = ""
        band_powers = None
        real_fs = None

        if len(window_data) < 2:
            valid, reason = 0, "buffer_corto"
        else:
            timestamps, values = zip(*window_data)
            # Serve almeno un segmento pieno di dati reali. Durata e non
            # conteggio campioni, per non dipendere da FS nominale.
            if timestamps[-1] - timestamps[0] < WELCH_NPERSEG_SECONDS:
                valid, reason = 0, "buffer_corto"
            # get_time_window garantisce che la finestra copra al piu'
            # WELCH_WINDOW_SECONDS, non che sia PIENA: con pacchetti BLE persi
            # restano meno campioni sullo stesso intervallo, e Welch li
            # leggerebbe come contigui.
            elif not self.window_is_continuous(timestamps):
                valid, reason = 0, "buffer_discontinuo"
            elif not self.window_quality_ok(timestamps[0], timestamps[-1]):
                valid, reason = 0, "qualita_bassa"
            else:
                real_fs = self.compute_real_fs(timestamps)
                # Riscalati sulla fs reale: a campioni fissi il segmento non
                # coprirebbe esattamente WELCH_NPERSEG_SECONDS di tempo reale.
                nperseg_real = max(2, round(WELCH_NPERSEG_SECONDS * real_fs))
                noverlap_real = min(nperseg_real - 1, round(WELCH_NOVERLAP_SECONDS * real_fs))
                band_powers = self.compute_band_powers(
                    np.array(values), fs=real_fs,
                    nperseg=nperseg_real, noverlap=noverlap_real)
                if band_powers is None:
                    valid, reason = 0, "welch_fallito"

        # Il plot resta attivo anche a registrazione ferma: il gating riguarda
        # solo la scrittura su file.
        if valid:
            for band in brainwave_bands:
                self.band_data_plot[band].append((timestamp, band_powers[band]))

        if valid and self.recording_active and self.bands_csv_writer is not None:
            # Due timestamp, entrambi riferiti all'estremo destro della
            # finestra Welch e nessuno dei due corretto con l'offset stimato:
            # timestamp_local e' il riferimento per la sincronizzazione con
            # Moodle, timestamp_idun e' l'unico legato al campionamento del
            # dispositivo. La coppia grezza lascia rifare la stima in analisi
            # sull'intera sessione.
            #
            # ts_local e' l'ancora letta all'arrivo del pacchetto, non
            # time.time() letto qui: leggerlo adesso includerebbe l'attesa del
            # tick di qualita' e il tempo di calcolo di Welch. Letto una volta
            # sola e riusato per CSV ed evento, cosi' non possono divergere.
            ts_local = self.packet_local_time(timestamp)
            self.bands_csv_writer.writerow([
                f"{ts_local:.6f}",
                f"{timestamp:.6f}",
                f"{band_powers['Delta']:.6g}",
                f"{band_powers['Theta']:.6g}",
                f"{band_powers['Alpha']:.6g}",
                f"{band_powers['Sigma']:.6g}",
                f"{band_powers['Beta']:.6g}",
                f"{band_powers['Gamma']:.6g}",
            ])
            self.bands_csv_file.flush()
            self.recording_rows += 1

            # Accodato subito dopo la scrittura, cosi' CSV e coda restano
            # allineati per indice. La cadenza la decide maybe_flush_chunk.
            self.pending_events.append(
                self.build_sample_event(ts_local, timestamp, band_powers))
            self.maybe_flush_chunk()
        elif not valid and self.recording_active:
            # Diagnostica locale: non viene scritta su file ne' inviata al
            # backend.
            self.recording_rejected[reason] += 1

        if DEBUG_BANDS:
            marker = "REC" if self.recording_active else "---"
            if valid:
                print(f"[BANDS {marker}] {self.t_rel(timestamp):.1f}s "
                      + " ".join(f"{b[:2]}={band_powers[b]:.4g}" for b in brainwave_bands)
                      + f" q={quality:.0f}", flush=True)
            else:
                print(f"[BANDS {marker}] {self.t_rel(timestamp):.1f}s scartato: {reason} (q={quality:.0f})", flush=True)
