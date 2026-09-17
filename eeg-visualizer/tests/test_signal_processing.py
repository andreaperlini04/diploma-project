"""
Test di SignalProcessingMixin: Welch, gating di qualita', t_rel.

Nessuna dipendenza dalla rete o dal backend: solo calcolo su segnali
sintetici, cosi' i test girano in millisecondi e non richiedono il
dispositivo IDUN ne' un backend attivo.
"""
import time

import numpy as np
import pytest

FS = 250
WELCH_NPERSEG = 750          # FS * 3, deve combaciare con config.py
WELCH_WINDOW_SAMPLES = 1500  # FS * 6, deve combaciare con config.py


def test_compute_band_powers_identifica_la_banda_dominante(visualizer):
    """
    Un seno puro a 10 Hz deve finire quasi interamente in Alpha (8-12 Hz):
    verifica che l'integrazione per banda sia effettivamente selettiva in
    frequenza, non solo che il codice giri senza eccezioni.
    """
    t = np.arange(0, 6, 1 / FS)
    signal = np.sin(2 * np.pi * 10 * t) * 20

    band_powers = visualizer.compute_band_powers(signal, fs=FS)

    assert max(band_powers, key=band_powers.get) == 'Alpha'
    # Le bande lontane da 10 Hz devono restare trascurabili rispetto ad Alpha
    assert band_powers['Gamma'] < band_powers['Alpha'] * 0.05


def test_compute_band_powers_buffer_troppo_corto_ritorna_none(visualizer):
    """
    Meno campioni di WELCH_NPERSEG: nessun risultato, non un'eccezione.
    """
    signal = np.zeros(10)
    assert visualizer.compute_band_powers(signal, fs=FS) is None


def test_compute_real_fs_su_campionamento_regolare(visualizer):
    """
    Timestamp equispaziati a FS=250 devono ridare ~250 Hz, entro tolleranza
    numerica minima (nessun campione mancante).
    """
    timestamps = [i / FS for i in range(1500)]
    assert visualizer.compute_real_fs(timestamps) == pytest.approx(FS, rel=1e-6)


def test_window_is_continuous_rileva_i_buchi(visualizer):
    """
    Una finestra con un salto temporale a meta' (pacchetti BLE persi) non
    deve essere considerata continua.
    """
    regular = [i / FS for i in range(100)]
    assert visualizer.window_is_continuous(regular, fs=FS) is True

    with_gap = regular[:50] + [t + 5.0 for t in regular[50:]]  # buco di 5s
    assert visualizer.window_is_continuous(with_gap, fs=FS) is False


def test_window_is_continuous_meno_di_due_campioni(visualizer):
    """
    Con meno di due campioni non esiste un intervallo da confrontare: il
    metodo deve rispondere False (non continua), non sollevare IndexError.
    """
    assert visualizer.window_is_continuous([], fs=FS) is False
    assert visualizer.window_is_continuous([1.0], fs=FS) is False


def test_window_is_continuous_tolleranza_ai_confini(visualizer):
    """
    La tolleranza e' max_gap_seconds di dati mancanti: un buco appena sotto
    deve passare, uno appena sopra no. Confine esplicito, altrimenti un
    errore di segno resterebbe invisibile.
    """
    regular = [i / FS for i in range(500)]

    quasi = regular[:250] + [t + 1.9 for t in regular[250:]]
    assert visualizer.window_is_continuous(quasi, fs=FS, max_gap_seconds=2.0) is True

    oltre = regular[:250] + [t + 2.1 for t in regular[250:]]
    assert visualizer.window_is_continuous(oltre, fs=FS, max_gap_seconds=2.0) is False


def test_window_is_continuous_soglia_permissiva_di_default(visualizer):
    """
    Il default e' deliberatamente permissivo: un buco di un secondo - che con
    la soglia storica di 249 campioni (~0,996 s) avrebbe fatto scartare la
    finestra - deve passare senza che il chiamante specifichi nulla.

    Fissa la scelta progettuale, non solo il valore: se WELCH_MAX_GAP_SECONDS
    venisse riportato sotto il secondo, questo test lo segnalerebbe.
    """
    from front_end.config import WELCH_MAX_GAP_SECONDS

    assert WELCH_MAX_GAP_SECONDS >= 1.0, (
        "soglia pensata per essere permissiva: sotto il secondo si torna al "
        "comportamento storico che scartava anche le perdite brevi")

    regular = [i / FS for i in range(500)]
    buco_breve = regular[:250] + [t + 1.0 for t in regular[250:]]
    assert visualizer.window_is_continuous(buco_breve, fs=FS) is True


def test_window_is_continuous_non_reagisce_alla_deriva(visualizer):
    """
    La deriva reale del dispositivo e' dell'ordine dei ppm: su una finestra
    da 6 s sposta il confronto di microsecondi, contro una tolleranza di
    quasi un secondo. Non deve mai produrre un falso positivo.

    E' il motivo per cui il controllo usa la fs NOMINALE: con quella stimata
    da compute_real_fs (1/intervallo medio) il confronto degenererebbe a zero
    per costruzione, rendendo il controllo cieco anche ai buchi veri - caso
    coperto dal test successivo.
    """
    fs_reale = FS * 1.00001  # +10 ppm
    timestamps = [i / fs_reale for i in range(WELCH_WINDOW_SAMPLES)]
    assert visualizer.window_is_continuous(timestamps, fs=FS) is True


def test_window_is_continuous_con_fs_stimata_sarebbe_cieco(visualizer):
    """
    Con la fs stimata dai timestamp stessi, (n-1)/fs coincide con la durata
    della finestra e la differenza e' identicamente zero: anche una finestra
    palesemente bucata risulterebbe continua. Fissato qui per impedire che un
    refactoring "uniformi" la chiamata passando real_fs.
    """
    regular = [i / FS for i in range(500)]
    with_gap = regular[:250] + [t + 5.0 for t in regular[250:]]

    # float(): compute_real_fs restituisce un np.float64, che propagandosi nel
    # confronto farebbe restituire np.bool_ invece di bool - vero ma non
    # identico a True.
    fs_stimata = float(visualizer.compute_real_fs(with_gap))

    assert visualizer.window_is_continuous(with_gap, fs=fs_stimata) is True, (
        "con la fs stimata il controllo e' cieco: e' esattamente il motivo "
        "per cui il codice di produzione usa FS nominale")
    assert visualizer.window_is_continuous(with_gap, fs=FS) is False


def test_t_rel_prima_dell_inizio_sessione(visualizer):
    """
    Senza session_start_ts impostato, t_rel deve restituire 0.0 invece di
    sollevare un'eccezione: capita nella finestra tra la creazione
    dell'istanza e il primo campione EEG ricevuto.
    """
    assert visualizer.session_start_ts is None
    assert visualizer.t_rel(12345.0) == 0.0


def test_t_rel_e_relativo_al_primo_campione(visualizer):
    visualizer.session_start_ts = 1000.0
    assert visualizer.t_rel(1006.5) == pytest.approx(6.5)


def test_window_quality_ok_nessun_tick_nella_finestra(visualizer):
    """
    Nessun tick di qualita' cade nell'intervallo richiesto: si assume
    permissivo (True), non si blocca per mancanza di dati. Capita ad
    esempio nei primissimi istanti, prima che arrivi il primo tick.
    """
    visualizer.quality_history.append((100.0, 90.0))  # fuori da [200, 210]
    assert visualizer.window_quality_ok(200.0, 210.0) is True


def test_window_quality_ok_tutti_sopra_soglia(visualizer):
    visualizer.quality_history.append((201.0, 80.0))
    visualizer.quality_history.append((205.0, 70.0))
    assert visualizer.window_quality_ok(200.0, 210.0) is True


def test_window_quality_ok_un_tick_sotto_soglia_scarta_la_finestra(visualizer):
    """
    Anche se il tick PIU' RECENTE e' sopra soglia, un solo tick scadente in
    un punto qualsiasi della finestra deve scartarla per intero - e' proprio
    lo scopo dichiarato nel docstring del metodo: un tratto di segnale
    scadente nel mezzo non deve passare solo perche' la qualita' e' poi
    migliorata prima della fine della finestra.
    """
    visualizer.quality_history.append((201.0, 90.0))  # buono
    visualizer.quality_history.append((205.0, 20.0))  # scadente, in mezzo
    visualizer.quality_history.append((209.0, 95.0))  # buono, il piu' recente
    assert visualizer.window_quality_ok(200.0, 210.0) is False


def test_window_quality_ok_soglia_e_esclusiva(visualizer):
    """
    Il confronto e' > QUALITY_SCORE_THRESHOLD, non >=: un tick esattamente
    alla soglia non deve passare.
    """
    from front_end.config import QUALITY_SCORE_THRESHOLD

    visualizer.quality_history.append((205.0, float(QUALITY_SCORE_THRESHOLD)))
    assert visualizer.window_quality_ok(200.0, 210.0) is False

    visualizer.quality_history.append((206.0, QUALITY_SCORE_THRESHOLD + 0.01))
    assert visualizer.window_quality_ok(206.0, 206.0) is True


def test_window_quality_ok_confini_inclusivi(visualizer):
    """
    Un tick esattamente su t_start o t_end deve contare come dentro la
    finestra: il confronto e' t_start <= ts <= t_end, non stretto.
    """
    visualizer.quality_history.append((200.0, 20.0))  # esattamente su t_start
    assert visualizer.window_quality_ok(200.0, 210.0) is False

    visualizer.quality_history.clear()
    visualizer.quality_history.append((210.0, 20.0))  # esattamente su t_end
    assert visualizer.window_quality_ok(200.0, 210.0) is False


def test_window_quality_ok_ignora_tick_fuori_finestra(visualizer):
    """
    Un tick scadente PRIMA o DOPO la finestra richiesta non deve influenzare
    il risultato: solo l'intervallo [t_start, t_end] conta.
    """
    visualizer.quality_history.append((100.0, 5.0))    # scadente, prima
    visualizer.quality_history.append((205.0, 90.0))   # buono, dentro
    visualizer.quality_history.append((300.0, 5.0))    # scadente, dopo
    assert visualizer.window_quality_ok(200.0, 210.0) is True


def _fill_continuous_window(visualizer, n_samples, fs=FS, base_ts=None):
    """
    Popola signal_data con n_samples campioni equispaziati a fs Hz, un seno
    a 10 Hz: segnale pulito, nessun buco, pensato per passare tutti i
    controlli di validita' salvo quello che il singolo test vuole violare.
    """
    if base_ts is None:
        base_ts = time.time()
    t = np.arange(n_samples) / fs
    sig = np.sin(2 * np.pi * 10 * t) * 20
    visualizer.signal_data.clear()
    visualizer.signal_data.extend(
        (base_ts + t[i], float(sig[i])) for i in range(n_samples)
    )
    if visualizer.session_start_ts is None:
        visualizer.session_start_ts = visualizer.signal_data[0][0]
    return base_ts


def _fill_gapped_window(visualizer, gap_s=3.0, half=500, fs=FS):
    """
    Due blocchi continui separati da un buco di gap_s, dimensionati perche' il
    buco cada DENTRO la finestra di get_time_window.

    Traslare in avanti la seconda meta' di un buffer pieno non basta:
    get_time_window seleziona per timestamp, quindi il primo blocco
    finirebbe fuori finestra e resterebbe solo il secondo, continuo e troppo
    corto, scartato come 'buffer_corto' senza esercitare il controllo di
    continuita'. Con due blocchi da 2 s separati da 3 s la finestra copre 6 s
    con circa 3 s di campioni.
    """
    base_ts = time.time()
    t = np.arange(half) / fs
    sig = np.sin(2 * np.pi * 10 * t) * 20

    visualizer.signal_data.clear()
    visualizer.signal_data.extend(
        (base_ts + t[i], float(sig[i])) for i in range(half)
    )
    offset = t[-1] + gap_s
    visualizer.signal_data.extend(
        (base_ts + offset + t[i], float(sig[i])) for i in range(half)
    )
    if visualizer.session_start_ts is None:
        visualizer.session_start_ts = visualizer.signal_data[0][0]
    return base_ts


def _mark_quality(visualizer, ts, quality=90.0):
    visualizer.quality_score.append(quality)
    visualizer.quality_history.append((ts, quality))


def test_scarto_buffer_corto(active_recording):
    """
    Meno di WELCH_NPERSEG campioni nel buffer: scartata come 'buffer_corto',
    mai passata a Welch.
    """
    _fill_continuous_window(active_recording, WELCH_NPERSEG - 1)
    _mark_quality(active_recording, active_recording.signal_data[-1][0])

    active_recording.log_band_powers(active_recording.signal_data[-1][0])

    assert active_recording.recording_rejected['buffer_corto'] == 1
    assert active_recording.recording_rows == 0


def test_scarto_buffer_discontinuo(active_recording):
    """
    Un buco nei timestamp all'interno della finestra: scartata come
    'buffer_discontinuo', anche se la finestra copre abbastanza tempo da
    superare il controllo di durata e la qualita' e' sopra soglia.

    E' il caso che get_time_window da solo non intercetta: seleziona per
    timestamp, quindi la finestra copre comunque 6 s reali, ma con meno
    campioni del dovuto. Welch, che i timestamp non li guarda, leggerebbe il
    buco come un gradino.
    """
    _fill_gapped_window(active_recording, gap_s=3.0)
    _mark_quality(active_recording, active_recording.signal_data[-1][0])

    active_recording.log_band_powers(active_recording.signal_data[-1][0])

    assert active_recording.recording_rejected['buffer_discontinuo'] == 1
    assert active_recording.recording_rows == 0
    assert active_recording.recording_rejected['buffer_corto'] == 0, (
        "il buco deve cadere dentro la finestra: se la finestra risultasse "
        "troppo corta il controllo di continuita' non sarebbe esercitato")


def test_scarto_qualita_bassa(active_recording):
    """
    Buffer pieno e continuo, ma con un tick di qualita' sotto soglia caduto
    nell'intervallo della finestra: scartata come 'qualita_bassa'.
    """
    _fill_continuous_window(active_recording, WELCH_WINDOW_SAMPLES)

    ts_start = active_recording.signal_data[0][0]
    ts_end = active_recording.signal_data[-1][0]
    active_recording.quality_history.append(((ts_start + ts_end) / 2, 20.0))
    active_recording.quality_score.append(20.0)

    active_recording.log_band_powers(ts_end)

    assert active_recording.recording_rejected['qualita_bassa'] == 1
    assert active_recording.recording_rows == 0


def test_finestra_valida_viene_registrata_senza_scarti(active_recording):
    """
    Buffer pieno, continuo, qualita' sopra soglia: la finestra deve essere
    accettata - riga scritta sul CSV, evento accodato per l'upload, nessuno
    scarto contato.
    """
    _fill_continuous_window(active_recording, WELCH_WINDOW_SAMPLES)
    _mark_quality(active_recording, active_recording.signal_data[-1][0])

    active_recording.log_band_powers(active_recording.signal_data[-1][0])

    assert active_recording.recording_rows == 1
    assert sum(active_recording.recording_rejected.values()) == 0
    assert len(active_recording.pending_events) == 1


def test_timestamp_local_e_quello_dell_arrivo_del_pacchetto(active_recording):
    """
    La riga deve portare l'orologio letto ALL'ARRIVO del pacchetto, non al
    momento della scrittura: fra i due istanti cadono l'attesa del tick di
    qualita' e il calcolo di Welch, che finirebbero dentro il timestamp usato
    per correlare con Moodle. La pausa simula quel divario.
    """
    _fill_continuous_window(active_recording, WELCH_WINDOW_SAMPLES)
    ts_end = active_recording.signal_data[-1][0]

    # Il pacchetto "arriva": qui viene letta l'ancora.
    active_recording.update_clock_offset()
    ancora = active_recording.last_packet_local_ts

    time.sleep(0.2)  # attesa del tick di qualita' + calcolo

    _mark_quality(active_recording, ts_end)
    active_recording.log_band_powers(ts_end)

    assert active_recording.recording_rows == 1
    evento = active_recording.pending_events[0]
    assert evento['timestamp'] == ancora, (
        "timestamp_local deve essere l'ancora del pacchetto, non una "
        "lettura fatta al momento della scrittura")
    assert evento['payload']['timestamp_idun'] == ts_end
    assert time.time() - ancora >= 0.2, (
        "senza un divario reale il test non distingue le due letture")


def test_timestamp_local_ricade_su_ora_senza_pacchetti(active_recording):
    """
    Se nessun pacchetto e' mai stato registrato dall'ancora - come nei test
    che popolano signal_data a mano - la riga usa comunque un orologio
    sensato invece di fallire.
    """
    _fill_continuous_window(active_recording, WELCH_WINDOW_SAMPLES)
    ts_end = active_recording.signal_data[-1][0]
    _mark_quality(active_recording, ts_end)

    assert active_recording.last_packet_local_ts is None
    before = time.time()
    active_recording.log_band_powers(ts_end)
    after = time.time()

    assert active_recording.recording_rows == 1
    assert before <= active_recording.pending_events[0]['timestamp'] <= after


def test_recording_rejected_accumula_per_motivo(active_recording):
    """
    recording_rejected e' un Counter: scarti ripetuti per lo stesso motivo
    si sommano, motivi diversi restano su chiavi separate.
    """
    for _ in range(2):
        _fill_continuous_window(active_recording, WELCH_NPERSEG - 1)
        _mark_quality(active_recording, active_recording.signal_data[-1][0])
        active_recording.log_band_powers(active_recording.signal_data[-1][0])

    _fill_continuous_window(active_recording, WELCH_WINDOW_SAMPLES)
    ts_end = active_recording.signal_data[-1][0]
    active_recording.quality_history.append((ts_end, 10.0))
    active_recording.quality_score.append(10.0)
    active_recording.log_band_powers(ts_end)

    assert active_recording.recording_rejected['buffer_corto'] == 2
    assert active_recording.recording_rejected['qualita_bassa'] == 1
    assert active_recording.recording_rows == 0


def test_scarto_non_contato_se_registrazione_non_attiva(visualizer):
    """
    Il plot real-time resta attivo anche a registrazione ferma (per design,
    vedi il commento nel codice), ma gli scarti non devono essere contati
    ne' deve essere scritta alcuna riga se recording_active e' False.

    Usa visualizer, non active_recording: qui serve proprio
    recording_active=False, il default di __init__.
    """
    assert visualizer.recording_active is False
    _fill_continuous_window(visualizer, WELCH_NPERSEG - 1)  # scarterebbe come buffer_corto
    _mark_quality(visualizer, visualizer.signal_data[-1][0])

    visualizer.log_band_powers(visualizer.signal_data[-1][0])

    assert sum(visualizer.recording_rejected.values()) == 0
    assert visualizer.recording_rows == 0