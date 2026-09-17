class Config:
    """Configurazione di default (sviluppo)."""

    DB_PATH = "sessions/timeline.db"
    HOST = "127.0.0.1"
    PORT = 8000          # porta attesa dal client EEG (BACKEND_URL del contratto)
    DEBUG = False

    # Limite alto apposta: il batch inviato allo Stop può valere qualche
    # centinaio di kB e non deve essere troncato.
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024


    ALLOWED_ORIGINS = [
        "https://upraisemoodle.dti.supsi.ch",  # Moodle SUPSI (remoto)
        "http://localhost:8080",                # Moodle locale in Docker
    ]


class TestConfig(Config):
    """Configurazione per i test. DB_PATH lo assegna la fixture 'app' in
    tests/conftest.py: i repository aprono una connessione per operazione,
    quindi con ':memory:' ognuna vedrebbe un database vuoto diverso."""

    DEBUG = True
    TESTING = True