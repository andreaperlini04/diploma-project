"""
Fixture condivise da tutti i test.

qapp: serve una QApplication prima di istanziare qualunque QWidget, anche
per testare solo la logica di calcolo. Scope 'session': PyQt6 non ne
permette piu' di una per processo.

visualizer: istanza pronta a registrare, con il CSV in una cartella
temporanea isolata. raw_visualizer: la stessa senza i default di comodo, per
i test sullo stato grezzo di __init__.

active_recording: abilita la scrittura su CSV senza passare da
start_recording(), che aprirebbe anche una sessione di rete.

fake_backend: un vero http.server locale, per testare l'upload contro un
endpoint reale invece di mockare urllib.
"""
import csv
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from PyQt6 import QtWidgets


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    yield app


def _make_visualizer(tmp_path, monkeypatch):
    # I CSV finiscono nella working directory: isolarli evita che i test
    # sporchino il progetto o interferiscano tra loro.
    monkeypatch.chdir(tmp_path)

    from front_end.EEGVisualizer import EEGVisualizer
    return EEGVisualizer(plot_FFT=True)


def _close_figures(v):
    # initUI crea due Figure per istanza: senza chiuderle si accumulano per
    # tutta la sessione di test ("too many figures" oltre la ventesima).
    import matplotlib.pyplot as plt
    plt.close(v.figure)
    plt.close(v.figure_fft)


@pytest.fixture
def visualizer(qapp, tmp_path, monkeypatch):
    v = _make_visualizer(tmp_path, monkeypatch)
    v.impedance_data = 1000
    v.last_fft_zscores = {'Alpha': 0.5}
    yield v
    _close_figures(v)


@pytest.fixture
def raw_visualizer(qapp, tmp_path, monkeypatch):
    v = _make_visualizer(tmp_path, monkeypatch)
    yield v
    _close_figures(v)


@pytest.fixture
def active_recording(visualizer):
    """
    Registrazione attiva con CSV aperto, senza invocare start_recording():
    quella chiamerebbe open_session_async, che tenterebbe una POST reale.
    """
    f = open("test_bands.csv", "w", newline="")
    writer = csv.writer(f, delimiter=';')
    writer.writerow([
        "timestamp_local", "timestamp_idun",
        "p_delta", "p_theta", "p_alpha", "p_sigma", "p_beta", "p_gamma",
    ])
    visualizer.bands_csv_file = f
    visualizer.bands_csv_writer = writer
    visualizer.recording_active = True
    visualizer.session_id = "test_session"
    yield visualizer
    f.close()


@pytest.fixture(autouse=True)
def _disable_ntp_check_by_default(monkeypatch):
    """
    NTP_CHECK_ENABLED=False per ogni test, salvo riattivazione esplicita.

    Altrimenti start_recording() lancia una query NTP reale in un thread
    daemon che, se la rete non risponde, resta in volo fino a 3 s oltre la
    durata del test. Se nel frattempo un test successivo ha ripuntato
    BACKEND_URL sul proprio fake_backend, quella POST tardiva ne contamina
    received_events.
    """
    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "NTP_CHECK_ENABLED", False)



class _FakeBackendState:
    """Stato condiviso tra il thread del server e il test che lo interroga."""

    def __init__(self):
        self.received_samples = []  # eventi 'sample' accettati, in ordine
        self.chunk_sizes = []       # dimensione di ogni POST accettata
        self.fail_next_n = 0        # quante prossime POST con sample rispondono 500
        # Ogni POST per intero, un elemento per richiesta: distingue "un'unica
        # POST con piu' eventi" da "piu' POST separate", cosa che
        # received_samples e chunk_sizes non permettono di vedere.
        self.received_events = []


@pytest.fixture
def fake_backend(monkeypatch):
    """
    Backend HTTP finto su porta libera (bind su 0), non sulla 8000 del
    backend vero: cosi' sono esclusi per costruzione sia un bind fallito
    mentre il Flask gira, sia la scrittura di dati sintetici nel database
    reale se il server finto non partisse.

    Il monkeypatch va su front_end.backend_client e non su front_end.config:
    il modulo ha gia' la propria copia del riferimento dall'import.
    """
    state = _FakeBackendState()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers['Content-Length'])
            events = json.loads(self.rfile.read(length))
            samples = [e for e in events if e['event_type'] == 'sample']

            if state.fail_next_n > 0 and samples:
                state.fail_next_n -= 1
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'ko')
                return

            state.received_events.append(events)
            if samples:
                state.received_samples.extend(samples)
                state.chunk_sizes.append(len(samples))

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok')

        def log_message(self, *args):
            pass  # silenzia il log di default di BaseHTTPRequestHandler

    server = HTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]

    import front_end.backend_client as backend_client
    monkeypatch.setattr(backend_client, "BACKEND_URL",
                         f"http://127.0.0.1:{port}/api/sessions")

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield state

    server.shutdown()


def wait_until_idle(visualizer, timeout=5.0):
    """
    Attende che l'upload in corso si concluda. I worker girano in thread
    daemon: senza attendere, un'asserzione leggerebbe lo stato prima che il
    thread abbia finito.
    """
    deadline = time.time() + timeout
    while visualizer.upload_in_flight and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.1)  # margine per l'ultima scrittura di stato