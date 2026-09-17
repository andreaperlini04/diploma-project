import sqlite3
from pathlib import Path
from threading import Lock

from app.models.timeline_entry import TimelineEntry


class TimelineRepository:
    """Unico punto che tocca la tabella 'timeline'. Nessuna logica di dominio qui."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS timeline (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT,
                    ts          REAL    NOT NULL,
                    source      TEXT    NOT NULL,
                    event_type  TEXT    NOT NULL,
                    payload     TEXT    NOT NULL,
                    description TEXT    NOT NULL DEFAULT '',
                    user_id INTEGER,
                    UNIQUE(session_id, source, event_type, ts)
                )
                """
            )
            # Migrazioni per i database creati prima di queste colonne. SQLite
            # non ha "ADD COLUMN IF NOT EXISTS": si tenta e si ignora l'errore.
            try:
                conn.execute("ALTER TABLE timeline ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            
            try:
                conn.execute("ALTER TABLE timeline ADD COLUMN user_id INTEGER")
            except sqlite3.OperationalError:
                pass

            # NB: per il vincolo UNIQUE le righe con session_id NULL sono
            # sempre distinte (NULL != NULL): gli eventi fuori sessione non
            # vengono mai scartati come duplicati.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timeline_session ON timeline(session_id, ts)"
            )

    def insert_many(self, entries: list[TimelineEntry]) -> int:
        """Inserimento bulk (usato per i chunk EEG). Idempotente: un chunk
        rispedito dopo un timeout di rete non duplica righe già presenti."""
        if not entries:
            return 0
        # L'ordine della tupla segue quello dell'elenco di colonne della
        # INSERT, non quello dei campi della dataclass.
        rows = [
            (e.session_id, e.ts, e.source, e.event_type, e.user_id, e.payload, e.description)
            for e in entries
        ]
        with self._lock, self._connect() as conn:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO timeline "
                "(session_id, ts, source, event_type, user_id, payload, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            return cur.rowcount

    def assign_user(self, session_id: str, user_id: int) -> int:
        """Attribuisce allo studente le righe della sessione rimaste scoperte.

        L'utente si impara in corsa, dopo che le righe sono già scritte. Una
        UPDATE per sessione, non per riga. Il filtro 'user_id IS NULL' non
        tocca mai un valore già scritto, quindi ripeterla è innocuo.

        Returns:
            int: righe attribuite ora.
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE timeline SET user_id = ? WHERE session_id = ? AND user_id IS NULL",
                (user_id, session_id),
            )
            return cur.rowcount

    def count_for_session(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM timeline WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row[0]