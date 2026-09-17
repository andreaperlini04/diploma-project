import json

from app.models.timeline_entry import TimelineEntry
from app.repository.clock_skew_repository import ClockSkewRepository
from app.repository.timeline_repository import TimelineRepository
from app.services.moodle_descriptions import describe
from app.services.session_service import SessionService


class TimelineService:
    """Logica di dominio per scrivere sulla timeline. Non sa nulla di Flask."""

    def __init__(
        self,
        timeline_repository: TimelineRepository,
        session_service: SessionService,
        clock_skew_repository: ClockSkewRepository,
    ):
        self._timeline_repo = timeline_repository
        self._session_service = session_service
        self._clock_skew_repo = clock_skew_repository

    def ingest(self, events: list) -> dict:
        """Registra un array di eventi nell'envelope comune alle due sorgenti:
        {"session_id", "timestamp", "source", "event_type", "payload"}.

        Un evento malformato è contato e saltato, non fa fallire la richiesta:
        il client non ritrasmette, un 400 su una riga costerebbe l'intera
        sessione (300-800 campioni). 'timestamp' è l'unico campo senza ripiego
        (vedi _coerce_ts). Idempotente sul vincolo UNIQUE (session_id, source,
        event_type, ts).

        Returns:
            dict: riepilogo (ricevuti, inseriti, duplicati, sessioni toccate).
        """
        entries: list[TimelineEntry] = []
        invalid = 0
        no_timestamp = 0
        skew_samples = 0
        opened: list[str] = []
        superseded: list[str] = []
        closed: list[str] = []
        registered: list[str] = []
        attributable: set[str] = set()

        for raw in events:
            if not isinstance(raw, dict):
                invalid += 1
                continue

            source = raw.get("source")
            event_type = raw.get("event_type")
            if not source or not event_type:
                invalid += 1
                continue

            ts = self._coerce_ts(raw.get("timestamp"))
            if ts is None:
                # Contatore separato da 'invalid': righe perse per timestamp
                # sono quasi sempre una regressione nella serializzazione del
                # client, diagnosticabile dalla sola risposta.
                no_timestamp += 1
                continue

            payload = raw.get("payload")
            if not isinstance(payload, dict):
                # Incapsulato invece che scartato: la colonna resta sempre un
                # JSON object e il dato non va perso.
                payload = {} if payload is None else {"value": payload}
            session_id = raw.get("session_id") or None
            description = raw.get("description")
            user_id = raw.get("user_id")
            if user_id is None and isinstance(payload.get("context"), dict):
                user_id = payload["context"].get("user_id")

            if event_type == "session_start":
                if not session_id:
                    # Senza id la sessione non è correlabile con Moodle:
                    # è il solo caso in cui l'evento è inutilizzabile.
                    invalid += 1
                    continue
                _, sup = self._session_service.open_session(session_id, ts)
                opened.append(session_id)
                if sup:
                    superseded.append(sup)

            elif event_type == "session_end":
                # Lo Stop si deduce di norma dall'arrivo del batch finale;
                # se il client invia esplicitamente session_end, l'evento
                # chiude comunque la sessione indicata.
                if session_id:
                    self._session_service.close_session(session_id, ts)
                    closed.append(session_id)

            elif event_type == "clock_skew_measured":
                # Telemetria sulla misura, non comportamento: tabella separata.
                self._clock_skew_repo.insert(
                    session_id=session_id or self._session_service.current_session_id(),
                    ts=ts,
                    skew_ms=payload.get("skew_ms", 0),
                    uncertainty_ms=payload.get("uncertainty_ms", 0),
                    rtt_min_ms=payload.get("rtt_min_ms", 0),
                    samples=payload.get("samples", 0),
                    payload=json.dumps(payload),
                )
                skew_samples += 1
                continue

            if source == "eeg":
                if not session_id:
                    invalid += 1
                    continue
                # Se la POST di session_start è fallita il client registra
                # comunque in locale e la sessione arriva solo allo Stop.
                if self._session_service.ensure_registered(session_id, ts):
                    registered.append(session_id)
            elif source == "moodle":
                # Il plugin non conosce il session_id: eredita quello della
                # sessione EEG attiva. Senza sessione la riga resta NULL invece
                # di essere scartata, è riallineabile per timestamp.
                session_id = session_id or self._session_service.current_session_id()
                if description is None:
                    description = describe(event_type, payload)
            else:
                # Nessuno dei due schemi di attribuzione si applica: scartato
                # invece di essere instradato come Moodle per esclusione.
                invalid += 1
                continue

            if session_id:
                # Attribuzione per sessione: il client EEG non conosce l'utente
                # Moodle, ma condivide il session_id con il plugin.
                if user_id is not None:
                    self._session_service.attach_user(session_id, user_id)
                else:
                    user_id = self._session_service.user_for(session_id)
                attributable.add(session_id)

            entries.append(
                TimelineEntry(
                    session_id=session_id,
                    ts=ts,
                    source=source,
                    event_type=event_type,
                    payload=json.dumps(payload),
                    description=description or "",
                    user_id=user_id, 
                )
            )

        inserted = self._timeline_repo.insert_many(entries)

        # Ripescaggio delle righe scritte prima che l'utente fosse noto:
        # session_start, i batch EEG anteriori all'attività nel browser e gli
        # eventi dello stesso lotto (le entry si assemblano prima dell'INSERT).
        attributed = 0
        for session_id in attributable:
            user_id = self._session_service.user_for(session_id)
            if user_id is not None:
                attributed += self._timeline_repo.assign_user(session_id, user_id)

        # row_count aggiornato dopo l'inserimento: un session_end può arrivare
        # nella stessa richiesta dei campioni che deve contare.
        for session_id in closed:
            self._session_service.update_row_count(
                session_id, self._timeline_repo.count_for_session(session_id)
            )

        return {
            "received": len(events),
            "stored": inserted,
            "duplicates": len(entries) - inserted,
            "invalid": invalid,
            "no_timestamp": no_timestamp,
            "clock_skew_samples": skew_samples,
            "rows_attributed": attributed,
            "sessions_opened": opened,
            "sessions_superseded": superseded,
            "sessions_closed": closed,
            "sessions_autoregistered": registered,
        }

    @staticmethod
    def _coerce_ts(value) -> float | None:
        """Timestamp del contratto: epoch in secondi, float.

        Tollera i millisecondi (il plugin lavora in ms interi): un epoch in
        secondi supera 1e11 solo nel 5138, 1e11 ms è il 1973, quindi la soglia
        discrimina senza ambiguità.

        Nessun ripiego sull'ora di arrivo, deliberato: il ritardo di rete è
        ignoto, un evento mal posizionato falsifica l'analisi in silenzio
        mentre uno mancante si conta in 'no_timestamp'.

        Returns:
            float | None: None se il valore è assente, non numerico o <= 0.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        value = float(value)
        if value <= 0:
            return None
        return value / 1000 if value > 1e11 else value