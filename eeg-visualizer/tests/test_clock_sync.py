"""
Test di ClockSyncMixin: stima dell'offset tra clock EEG e orologio macchina.

signal_data viene popolato a mano invece che tramite il dispositivo reale:
update_clock_offset legge solo l'ultimo campione, quindi basta un singolo
punto (now, ts_eeg) per esercitare la logica.
"""
import time

import pytest


def test_offset_stimato_e_coerente_con_il_ritardo_reale(visualizer):
    """
    Un campione con timestamp EEG noto, arrivato "ora": l'offset stimato deve
    coincidere con la differenza reale, entro pochi millisecondi di jitter
    del test stesso.
    """
    now = time.time()
    ts_eeg = now - 0.500  # il campione EEG e' "in ritardo" di 500ms
    visualizer.signal_data.append((ts_eeg, 0.0))

    visualizer.update_clock_offset()

    offset = visualizer.get_clock_offset()
    assert offset == pytest.approx(0.500, abs=0.05)


def test_get_clock_offset_none_senza_campioni(visualizer):
    """
    Prima che arrivi il primo pacchetto EEG, get_clock_offset non deve
    sollevare un'eccezione: deve segnalare "non ancora disponibile".
    """
    assert visualizer.get_clock_offset() is None


def test_to_local_time_usa_fallback_senza_offset(visualizer):
    """
    Senza offset stimabile, to_local_time ricade su time.time() invece di
    propagare l'assenza di dato: capita solo prima del primo pacchetto EEG,
    mai a registrazione avviata.
    """
    before = time.time()
    result = visualizer.to_local_time(12345.0)
    after = time.time()
    assert before <= result <= after


def test_to_local_time_applica_l_offset_stimato(visualizer):
    now = time.time()
    ts_eeg = now - 1.0
    visualizer.signal_data.append((ts_eeg, 0.0))
    visualizer.update_clock_offset()

    converted = visualizer.to_local_time(ts_eeg)
    assert converted == pytest.approx(now, abs=0.05)


def test_packet_local_time_usa_fallback_senza_pacchetti(visualizer):
    """
    Prima del primo pacchetto l'ancora non esiste: packet_local_time deve
    ricadere su time.time() invece di sollevare, come fa to_local_time.
    """
    before = time.time()
    result = visualizer.packet_local_time(12345.0)
    after = time.time()
    assert before <= result <= after


def test_packet_local_time_restituisce_la_lettura_del_pacchetto(visualizer):
    """
    Il valore e' l'orologio letto ALL'ARRIVO del pacchetto, non al momento
    della chiamata: senza l'ancora il risultato scivolerebbe in avanti dei
    200 ms della pausa.
    """
    ts_eeg = time.time() - 0.300
    visualizer.signal_data.append((ts_eeg, 0.0))
    visualizer.update_clock_offset()
    atteso = visualizer.last_packet_local_ts

    time.sleep(0.2)

    assert visualizer.packet_local_time(ts_eeg) == atteso
    assert time.time() - atteso >= 0.2, (
        "la pausa deve creare un divario reale, altrimenti il test non "
        "distingue l'ancora da una lettura fatta ora")


def test_packet_local_time_estrapola_su_un_campione_diverso(visualizer):
    """
    Chiamata con un timestamp EEG diverso dall'ancora: il risultato si sposta
    della stessa differenza, misurata sul clock EEG.

    Oggi non capita - log_band_powers data la finestra sull'ultimo campione,
    lo stesso su cui l'ancora e' stata presa - ma la forma generale evita che
    un cambiamento futuro produca in silenzio un timestamp sbagliato.
    """
    ts_eeg = time.time() - 1.0
    visualizer.signal_data.append((ts_eeg, 0.0))
    visualizer.update_clock_offset()
    ancora = visualizer.last_packet_local_ts

    assert visualizer.packet_local_time(ts_eeg - 0.5) == pytest.approx(ancora - 0.5)
    assert visualizer.packet_local_time(ts_eeg + 0.5) == pytest.approx(ancora + 0.5)


def test_estimate_drift_none_con_pochi_punti(visualizer):
    """
    Sotto SYNC_DRIFT_MIN_POINTS non c'e' abbastanza storia per un fit
    lineare affidabile: deve restituire None, non una stima rumorosa.
    """
    assert visualizer.estimate_drift() is None


def test_estimate_drift_none_esattamente_sotto_soglia(visualizer):
    """
    Confine esatto: SYNC_DRIFT_MIN_POINTS - 1 punti deve dare ancora None.
    Il confronto nel codice e' len(...) < SYNC_DRIFT_MIN_POINTS: un errore di
    off-by-one qui accetterebbe un fit su una storia troppo corta.
    """
    from front_end.config import SYNC_DRIFT_MIN_POINTS

    visualizer.offset_history = [(float(i), 0.05) for i in range(SYNC_DRIFT_MIN_POINTS - 1)]
    assert visualizer.estimate_drift() is None


def test_estimate_drift_offset_decrescente_da_ppm_positivo(visualizer):
    """
    Storia perfettamente lineare, cosi' il fit deve riprodurre esattamente i
    coefficienti scelti. Un offset decrescente significa griglia SDK piu'
    veloce del tempo reale, cioe' fs fisica > FS: per il segno in
    estimate_drift si traduce in ppm positivo.
    """
    from front_end.config import FS

    t0 = 1_700_000_000.0
    slope = -1e-5  # secondi di offset perduti per ogni secondo reale
    intercept = 0.050
    visualizer.offset_history = [
        (t0 + i * 100, intercept + slope * (i * 100)) for i in range(10)
    ]

    drift = visualizer.estimate_drift()

    assert drift is not None
    assert drift['n_points'] == 10
    assert drift['span_s'] == pytest.approx(900.0)
    assert drift['ppm'] == pytest.approx(10.0, abs=1e-6)
    assert drift['fs_implied'] == pytest.approx(FS * 1.00001, rel=1e-9)
    assert drift['error_15min_s'] == pytest.approx(0.009, abs=1e-9)


def test_estimate_drift_offset_crescente_da_ppm_negativo(visualizer):
    """
    Speculare al test precedente: offset che CRESCE nel tempo deve dare ppm
    negativo e fs_implied < FS - verifica che il segno non sia stato
    verificato per un solo verso per caso.
    """
    from front_end.config import FS

    t0 = 1_700_000_000.0
    slope = 2e-5
    intercept = 0.0
    visualizer.offset_history = [
        (t0 + i * 100, intercept + slope * (i * 100)) for i in range(10)
    ]

    drift = visualizer.estimate_drift()

    assert drift['ppm'] == pytest.approx(-20.0, abs=1e-6)
    assert drift['fs_implied'] < FS