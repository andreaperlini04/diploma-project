"""
Costanti di configurazione condivise dai moduli del visualizzatore EEG.
Raccolte qui perche' sono parametri sperimentali: cambiarli in un punto solo
vale per tutta la pipeline.
"""

FS = 250

# COSTANTI per grafici
window_size = 30
PLOT_WINDOW_SECONDS = 120
window_size_fft = PLOT_WINDOW_SECONDS
window_size_signal = window_size * FS
window_size_imu = window_size_signal // 10
image_size = 100
hold_duration = 500

QUALITY_SCORE_THRESHOLD = 50

# COSTANTI per calcolo potenze.
#
# I valori in secondi sono la vera unita' di significato. Quelli in campioni
# restano solo come default nominali: signal_processing.log_band_powers li
# ricalcola sulla fs reale stimata dalla finestra (vedi compute_real_fs).
WELCH_WINDOW_SECONDS = 6
WELCH_NPERSEG_SECONDS = 3
WELCH_NOVERLAP_SECONDS = 2

WELCH_WINDOW_SAMPLES = FS * WELCH_WINDOW_SECONDS
WELCH_NPERSEG = FS * WELCH_NPERSEG_SECONDS
WELCH_NOVERLAP = FS * WELCH_NOVERLAP_SECONDS

# Dati mancanti tollerati dentro una finestra Welch prima di scartarla come
# discontinua (signal_processing.window_is_continuous).
WELCH_MAX_GAP_SECONDS = 2

BASELINE_DURATION_SECONDS = 90
CLI_SMOOTHING_SECONDS = 30

DEBUG_CLI = True  # Log del calcolo CLI; ininfluente finche' il CLI resta scollegato
DEBUG_BANDS = True  # Log delle potenze assolute di banda

# Oltre alla stampa, governa l'accumulo di offset_history: con False
# estimate_drift restituisce sempre None.
DEBUG_SYNC = True

# Finestra su cui viene stimato l'offset tra clock EEG e orologio macchina.
# La stima e' il MINIMO di (time.time() - ts_eeg): il ritardo di consegna e'
# sempre additivo, quindi il minimo scarta il jitter BLE.
SYNC_OFFSET_WINDOW_SECONDS = 30
SYNC_LOG_INTERVAL_SECONDS = 10
SYNC_DRIFT_MIN_POINTS = 6  # punti minimi prima di stimare la deriva

# Backend locale
BACKEND_URL = "http://127.0.0.1:8000/api/v1/events"
BACKEND_TIMEOUT_SECONDS = 10
UPLOAD_ENABLED = True  # False per registrare solo in locale senza invio

# Soglia di partenza di un chunk incrementale, in righe scritte e non in
# tempo trascorso: le finestre scartate non producono eventi, quindi un
# tratto di segnale scadente non genera chunk vuoti.
UPLOAD_CHUNK_ROWS = 15

# Cartella dei CSV di sessione, invece della working directory di main.py.
LOG_DIR = "logs"

# Limiti fissi dell'asse y delle potenze assolute (scala log). In stato
# stazionario i valori reali stanno in 0.25-4300 uV^2, con un ordine di
# grandezza di margine per lato. Fissi anziche' autoscale: un transitorio da
# impedenza appena connessa vale 1e6+ e schiaccerebbe il resto della sessione.
POWER_YLIM_MIN = 0.1
POWER_YLIM_MAX = 1e4

# Verifica dell'orologio di sistema tramite NTP. La libreria MISURA lo
# scostamento, non corregge il clock: serve a documentare che il riferimento
# era attendibile, non a renderlo tale.
NTP_CHECK_ENABLED = True
NTP_SERVER = "pool.ntp.org"
NTP_TIMEOUT_SECONDS = 3

# Estremi in Hz, intervalli semiaperti [f_low, f_high). Sigma e Beta si
# sovrappongono fra 13 e 15 Hz: le bande non sono una partizione e la loro
# somma conta due volte quella regione.
brainwave_bands = {
    'Delta': (0.5, 4),
    'Theta': (4, 8),
    'Alpha': (8, 12),
    'Sigma': (12, 15),
    'Beta':  (13, 30),
    'Gamma': (30, 35)
}

band_colors = {
    'Delta': '#A4C2F4',
    'Theta': '#76D7C4',
    'Alpha': '#B6D7A8',
    'Sigma': '#F9CB9C',
    'Beta': '#F6A5A5',
    'Gamma': '#DDA0DD'
}

imu_colors = {
    'x': 'r',
    'y': 'g',
    'z': 'b'
}
