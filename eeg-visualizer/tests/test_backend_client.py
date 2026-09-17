"""
Test di BackendClientMixin: apertura sessione, upload a chunk, fallback.

Usa fake_backend invece di mockare urllib, cosi' i test coprono cadenza,
avanzamento del cursore e ripresa dopo un fallimento, non solo che una
funzione sia stata chiamata con certi argomenti.
"""
import time

import numpy as np

from conftest import wait_until_idle

FS = 250
CHUNK_ROWS = 15  # deve combaciare con UPLOAD_CHUNK_ROWS in config.py


def _feed_valid_sample(visualizer):
    """
    Inietta un campione valido e chiama log_band_powers, come farebbe
    l'handler delle predizioni a ogni tick di qualita'. Bypassa device e SDK.

    La pausa finale non e' cosmetica: signal_data viene popolato a mano senza
    passare da update_clock_offset, quindi packet_local_time ricade su
    time.time(), che su Windows ha risoluzione del millisecondo. Senza pausa
    due iterazioni consecutive ricadrebbero nello stesso tick di clock e
    riceverebbero lo stesso timestamp. Nella realta' i tick dell'SDK distano
    circa un secondo.
    """
    now = time.time()
    t = np.arange(0, 6, 1 / FS)
    signal = np.sin(2 * np.pi * 10 * t) * 20
    visualizer.signal_data.clear()
    visualizer.signal_data.extend(
        (now + i / FS, float(signal[i])) for i in range(len(t))
    )
    if visualizer.session_start_ts is None:
        visualizer.session_start_ts = visualizer.signal_data[0][0]
    visualizer.quality_score.append(90.0)
    visualizer.quality_history.append((visualizer.signal_data[-1][0], 90.0))
    visualizer.log_band_powers(visualizer.signal_data[-1][0])
    time.sleep(0.005)  # margine di sicurezza sulla risoluzione del clock


def _wait_for_post_count(fake_backend, n, timeout=5.0):
    """
    Attende che il backend finto abbia accettato almeno n richieste.

    wait_until_idle non basta per session_end: quando parte da solo passa da
    post_events_async, che non tocca upload_in_flight, l'unico flag che
    wait_until_idle osserva.
    """
    deadline = time.time() + timeout
    while len(fake_backend.received_events) < n and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.1)  # margine: intercetta anche una POST di troppo


def _session_end_events(fake_backend):
    """Tutti i session_end accettati, appiattiti su tutte le POST."""
    return [e for post in fake_backend.received_events
            for e in post if e['event_type'] == 'session_end']


def test_chunk_parte_solo_al_raggiungimento_della_soglia(visualizer, fake_backend):
    visualizer.start_recording()
    wait_until_idle(visualizer)  # attende la POST di session_start

    for _ in range(CHUNK_ROWS - 1):
        _feed_valid_sample(visualizer)
    assert fake_backend.chunk_sizes == [], (
        "nessun chunk deve partire sotto soglia")

    _feed_valid_sample(visualizer)
    wait_until_idle(visualizer)
    assert fake_backend.chunk_sizes == [CHUNK_ROWS]
    assert visualizer.upload_cursor == CHUNK_ROWS


def test_cursore_non_avanza_su_chunk_fallito(visualizer, fake_backend):
    visualizer.start_recording()
    wait_until_idle(visualizer)

    fake_backend.fail_next_n = 1
    for _ in range(CHUNK_ROWS):
        _feed_valid_sample(visualizer)
    wait_until_idle(visualizer)

    assert visualizer.upload_cursor == 0, (
        "un chunk fallito non deve avanzare il cursore")
    assert len(visualizer.pending_events) - visualizer.upload_cursor == CHUNK_ROWS, (
        "gli eventi del chunk fallito devono restare in coda per il retry")


def test_eventi_falliti_vengono_recuperati_senza_duplicati(visualizer, fake_backend):
    visualizer.start_recording()
    wait_until_idle(visualizer)

    fake_backend.fail_next_n = 1
    for _ in range(CHUNK_ROWS):
        _feed_valid_sample(visualizer)
    wait_until_idle(visualizer)
    assert visualizer.upload_cursor == 0

    # I 15 falliti sono gia' sopra soglia: il prossimo campione valido fa
    # ripartire subito un chunk che li include.
    _feed_valid_sample(visualizer)
    wait_until_idle(visualizer)

    assert visualizer.upload_cursor == CHUNK_ROWS + 1
    timestamps = [e['timestamp'] for e in fake_backend.received_samples]
    assert len(timestamps) == len(set(timestamps)), "nessun duplicato atteso"


def test_flush_finale_invia_il_residuo_sotto_soglia(visualizer, fake_backend):
    visualizer.start_recording()
    wait_until_idle(visualizer)

    n_residuo = 4
    assert n_residuo < CHUNK_ROWS
    for _ in range(n_residuo):
        _feed_valid_sample(visualizer)
    assert fake_backend.chunk_sizes == [], "sotto soglia, nessun chunk periodico"

    visualizer.stop_recording()
    wait_until_idle(visualizer)

    assert visualizer.upload_cursor == n_residuo
    assert fake_backend.chunk_sizes == [n_residuo]


def test_recupero_via_chunk_finale_quando_il_backend_torna_su(visualizer, fake_backend):
    """
    Backend giu' per tutta la sessione ma di nuovo disponibile prima dello
    Stop: il chunk finale recupera tutto in un'unica POST e _upload_worker
    non viene mai chiamato.
    """
    visualizer.start_recording()
    wait_until_idle(visualizer)

    fake_backend.fail_next_n = 999  # backend "giu'" per tutta la sessione
    n_campioni = 20
    for _ in range(n_campioni):
        _feed_valid_sample(visualizer)
    wait_until_idle(visualizer)
    assert visualizer.upload_cursor == 0

    fake_backend.fail_next_n = 0  # il backend torna disponibile prima dello Stop
    visualizer.stop_recording()
    wait_until_idle(visualizer)

    assert sum(fake_backend.chunk_sizes) == n_campioni, (
        "il chunk finale deve recuperare esattamente i campioni della "
        "sessione, una volta sola")
    assert visualizer.recording_rows == n_campioni


def test_fallback_su_csv_quando_anche_il_chunk_finale_fallisce(visualizer, fake_backend, monkeypatch):
    """
    Backend irraggiungibile anche durante il chunk finale: solo qui scatta la
    rilettura del CSV.

    La soglia dei chunk periodici e' alzata oltre il numero di campioni cosi'
    che durante il feed non ne parta nessuno; altrimenti quanti riescono a
    partire dipende dalla velocita' della rete locale e le asserzioni sul
    conteggio delle POST diventano instabili.
    """
    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "UPLOAD_CHUNK_ROWS", 10_000)

    visualizer.start_recording()
    wait_until_idle(visualizer)

    n_campioni = 20
    fake_backend.fail_next_n = 1  # fa fallire solo il tentativo di chunk finale
    for _ in range(n_campioni):
        _feed_valid_sample(visualizer)
    assert fake_backend.chunk_sizes == [], (
        "soglia alzata oltre n_campioni: nessun chunk periodico deve partire")

    visualizer.stop_recording()
    wait_until_idle(visualizer, timeout=8.0)

    # upload_cursor resta 0: _upload_worker consegna i dati ma non lo tocca,
    # e' un percorso a parte rispetto al meccanismo a cursore dei chunk. Non
    # e' un bug: e' l'indicatore che la consegna e' passata dal fallback, non
    # dal normale avanzamento a chunk.
    assert visualizer.upload_cursor == 0
    assert len(fake_backend.chunk_sizes) == 1, (
        "un'unica POST riuscita: quella del fallback, dopo il fallimento "
        "del chunk finale")
    assert fake_backend.chunk_sizes == [n_campioni], (
        "il fallback rilegge e reinvia TUTTI i campioni della sessione in "
        "un colpo solo, non solo il residuo dell'ultimo chunk fallito")


def test_finale_fallito_con_chunk_gia_confermati_non_attiva_fallback(visualizer, fake_backend, monkeypatch):
    """
    Ramo gemello del test precedente: con almeno un chunk gia' confermato e
    il chunk finale fallito, il fallback automatico non deve scattare.

    upload_cursor e' impostato direttamente perche' qui interessa solo la
    decisione presa in base al suo valore; farlo scaturire da un ciclo reale
    reintrodurrebbe la dipendenza dal timing della rete.
    """
    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "UPLOAD_CHUNK_ROWS", 10_000)

    visualizer.start_recording()
    wait_until_idle(visualizer)

    n_campioni = 20
    for _ in range(n_campioni):
        _feed_valid_sample(visualizer)
    assert fake_backend.chunk_sizes == [], "soglia alzata: nessun chunk periodico deve partire"

    visualizer.upload_cursor = 12  # simula 12 campioni gia' confermati da un chunk precedente

    upload_worker_calls = []
    original_upload_worker = visualizer._upload_worker

    def spy(*args, **kwargs):
        upload_worker_calls.append((args, kwargs))
        return original_upload_worker(*args, **kwargs)

    monkeypatch.setattr(visualizer, "_upload_worker", spy)

    fake_backend.fail_next_n = 1  # fa fallire il chunk finale (residuo di 8)
    visualizer.stop_recording()
    wait_until_idle(visualizer, timeout=8.0)

    assert upload_worker_calls == [], (
        "con upload_cursor > 0 il fallback automatico non deve scattare")
    assert visualizer.upload_cursor == 12, (
        "il cursore non deve avanzare ne' essere alterato da un chunk "
        "finale fallito")
    assert fake_backend.chunk_sizes == [], (
        "il chunk finale e' fallito e nessun fallback e' partito: nessuna "
        "POST deve risultare consegnata con successo")



def test_build_sample_event_ha_l_envelope_atteso(visualizer):
    """Contratto condiviso con il plugin Moodle, fissato senza rete."""
    visualizer.session_id = "sessione_di_test"
    band_powers = {'Delta': 1.0, 'Theta': 2.0, 'Alpha': 3.0,
                   'Sigma': 4.0, 'Beta': 5.0, 'Gamma': 6.0}

    event = visualizer.build_sample_event(1000.5, 999.9, band_powers)

    assert event == {
        'session_id': "sessione_di_test",
        'timestamp': 1000.5,
        'source': 'eeg',
        'event_type': 'sample',
        'payload': {
            'timestamp_idun': 999.9,
            'delta': 1.0, 'theta': 2.0, 'alpha': 3.0,
            'sigma': 4.0, 'beta': 5.0, 'gamma': 6.0,
        },
    }


def test_build_session_end_event_ha_l_envelope_atteso(visualizer):
    """
    Contratto dell'evento di chiusura. I quattro campi sono obbligatori lato
    backend: se uno manca la riga viene scartata in silenzio e la sessione
    resta aperta, cioe' il problema che session_end risolve.
    """
    visualizer.recording_rows = 42

    event = visualizer.build_session_end_event("sessione_di_test", 2000.5)

    assert event == {
        'session_id': "sessione_di_test",
        'timestamp': 2000.5,
        'source': 'eeg',
        'event_type': 'session_end',
        'payload': {'rows_local': 42},
    }


def test_session_end_accodato_al_chunk_finale_in_unica_post(visualizer, fake_backend):
    """
    Lo Stop deve produrre UNA sola POST, con session_end in coda ai campioni:
    il backend calcola row_count dopo aver inserito il lotto, quindi un
    session_end anticipato li lascerebbe fuori dal conteggio.
    """
    visualizer.start_recording()
    wait_until_idle(visualizer)  # POST di session_start
    assert len(fake_backend.received_events) == 1

    n_residuo = 4
    assert n_residuo < CHUNK_ROWS, "sotto soglia: nessun chunk periodico"
    for _ in range(n_residuo):
        _feed_valid_sample(visualizer)

    visualizer.stop_recording()
    wait_until_idle(visualizer)
    _wait_for_post_count(fake_backend, 2)

    assert len(fake_backend.received_events) == 2, (
        "campioni residui e session_end devono viaggiare in UN'UNICA POST")

    finale = fake_backend.received_events[1]
    assert [e['event_type'] for e in finale] == ['sample'] * n_residuo + ['session_end'], (
        "session_end deve essere l'ULTIMO evento dell'array, dopo i campioni")

    session_end = finale[-1]
    assert session_end['session_id'] == visualizer.session_id, (
        "senza lo stesso session_id del session_start il backend non trova "
        "la sessione da chiudere")
    assert session_end['timestamp'] == visualizer.recording_stop_ts, (
        "la fine e' il momento dello Stop, non quello dell'invio")
    assert session_end['source'] == 'eeg'
    assert session_end['payload']['rows_local'] == n_residuo


def test_session_end_inviato_anche_senza_alcun_campione(visualizer, fake_backend):
    """
    start_recording ha gia' mandato session_start, quindi la sessione esiste
    sul backend: senza session_end resterebbe aperta a tempo indeterminato e
    attirerebbe ogni evento Moodle successivo.
    """
    visualizer.start_recording()
    wait_until_idle(visualizer)

    visualizer.stop_recording()
    _wait_for_post_count(fake_backend, 2)

    assert visualizer.recording_rows == 0
    session_ends = _session_end_events(fake_backend)
    assert len(session_ends) == 1, (
        "session_end deve partire da solo anche senza campioni da inviare")
    assert session_ends[0]['session_id'] == visualizer.session_id
    assert session_ends[0]['payload']['rows_local'] == 0


def test_session_end_parte_comunque_se_il_chunk_finale_fallisce(visualizer, fake_backend, monkeypatch):
    """
    Chunk finale fallito con chunk gia' confermati: i residui restano
    recuperabili a mano dal CSV, ma la sessione va chiusa lo stesso. Dei due
    danni si sceglie il minore: row_count sottostimato si riconosce dal
    confronto con rows_local, una sessione aperta no.
    """
    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "UPLOAD_CHUNK_ROWS", 10_000)

    visualizer.start_recording()
    wait_until_idle(visualizer)

    for _ in range(20):
        _feed_valid_sample(visualizer)
    visualizer.upload_cursor = 12  # simula 12 campioni gia' confermati

    fake_backend.fail_next_n = 1  # fa fallire il chunk finale (residuo di 8)
    visualizer.stop_recording()
    wait_until_idle(visualizer, timeout=8.0)
    _wait_for_post_count(fake_backend, 2)

    assert fake_backend.chunk_sizes == [], "nessun campione deve risultare consegnato"
    session_ends = _session_end_events(fake_backend)
    assert len(session_ends) == 1, (
        "la chiusura deve essere ritentata da sola dopo il chunk finale fallito")
    assert session_ends[0]['payload']['rows_local'] == 20, (
        "rows_local riporta i campioni scritti in locale, non quelli "
        "consegnati: e' il termine di paragone che rivela la perdita")


def test_session_end_accodato_anche_al_fallback_su_csv(visualizer, fake_backend, monkeypatch):
    """
    Percorso di fallback (upload_cursor == 0, chunk finale fallito): la
    rilettura del CSV deve accodare session_end ai campioni ricostruiti,
    mantenendo l'unica POST e l'ordine corretto per row_count.
    """
    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "UPLOAD_CHUNK_ROWS", 10_000)

    visualizer.start_recording()
    wait_until_idle(visualizer)

    n_campioni = 20
    fake_backend.fail_next_n = 1  # fa fallire solo il chunk finale
    for _ in range(n_campioni):
        _feed_valid_sample(visualizer)

    visualizer.stop_recording()
    wait_until_idle(visualizer, timeout=8.0)
    _wait_for_post_count(fake_backend, 2)

    fallback = fake_backend.received_events[-1]
    assert [e['event_type'] for e in fallback] == ['sample'] * n_campioni + ['session_end'], (
        "il fallback deve reinviare tutti i campioni e chiudere la sessione "
        "nella stessa POST, con session_end in coda")
    assert len(_session_end_events(fake_backend)) == 1


def test_session_start_e_ntp_check_in_unica_post(visualizer, fake_backend, monkeypatch):
    """
    session_start e ntp_check devono viaggiare nella STESSA POST.

    Unico test che riattiva NTP_CHECK_ENABLED e fa una query reale verso
    pool.ntp.org. Senza rete ntp_check non compare, e la verifica su
    session_start resta valida: e' lo stesso "un fallimento NTP non blocca la
    sessione" garantito dal codice di produzione.
    """
    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "NTP_CHECK_ENABLED", True)

    visualizer.open_session_async("sessione_ntp_test", 1000.0)

    # Ne' upload_in_flight ne' un flag dedicato segnalano il completamento di
    # QUESTO invio (a differenza dei chunk, che lo usano): si attende finche'
    # arriva qualcosa o scade il timeout, che copre anche il caso peggiore
    # della query NTP (fino a NTP_TIMEOUT_SECONDS).
    deadline = time.time() + 5.0
    while not fake_backend.received_events and time.time() < deadline:
        time.sleep(0.05)

    assert len(fake_backend.received_events) == 1, (
        "session_start (ed eventuale ntp_check) devono arrivare in "
        "UN'UNICA richiesta POST, non in POST separate")

    posted = fake_backend.received_events[0]
    posted_types = {e['event_type'] for e in posted}
    assert 'session_start' in posted_types

    session_start = next(e for e in posted if e['event_type'] == 'session_start')
    assert session_start['session_id'] == "sessione_ntp_test"
    assert session_start['timestamp'] == 1000.0
    assert session_start['source'] == 'eeg'

    if 'ntp_check' in posted_types:
        ntp_check = next(e for e in posted if e['event_type'] == 'ntp_check')
        assert ntp_check['session_id'] == "sessione_ntp_test"
        assert set(ntp_check['payload']) == {'offset_s', 'delay_s', 'server'}
        assert visualizer.ntp_offset_s == ntp_check['payload']['offset_s'], (
            "self.ntp_offset_s deve riflettere l'ultima misura inviata")