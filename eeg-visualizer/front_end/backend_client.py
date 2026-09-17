"""
Comunicazione con il backend locale: apertura sessione, verifica NTP, invio
incrementale a chunk e fallback su CSV alla chiusura.

Tutte le operazioni di rete girano in thread separati, altrimenti una
richiesta lenta bloccherebbe i grafici fino al timeout.

L'invio segue un modello a cursore invece che a coda: gli eventi non vengono
rimossi dopo l'invio, avanza un indice che segna fino a dove il backend ha
confermato. Un chunk fallito non richiede quindi una struttura di retry e non
puo' generare duplicati.
"""

import csv
import json
import threading
import time
import urllib.error
import urllib.request

from .config import (
    BACKEND_TIMEOUT_SECONDS,
    BACKEND_URL,
    NTP_CHECK_ENABLED,
    NTP_SERVER,
    NTP_TIMEOUT_SECONDS,
    UPLOAD_CHUNK_ROWS,
    UPLOAD_ENABLED,
)


class BackendClientMixin:
    """
    Invio verso il backend. Mixin: usa upload_status_update e
    recording_status definiti in EEGVisualizer. I widget non vengono mai
    toccati dai thread di rete, l'esito passa per il segnale.
    """

    def open_session_async(self, session_id, start_ts):
        """Apre la sessione sul backend in un thread separato."""
        thread = threading.Thread(
            target=self._open_session_worker, args=(session_id, start_ts), daemon=True)
        thread.start()

    def _open_session_worker(self, session_id, start_ts):
        """
        Misura lo scostamento NTP e invia session_start con l'eventuale
        ntp_check in una sola POST.

        La misura NTP verifica il clock, non lo corregge: impostare l'ora di
        sistema richiede privilegi di amministratore. Un fallimento della
        query non impedisce l'invio di session_start.
        """
        events = [{
            'session_id': session_id,
            'timestamp': start_ts,
            'source': 'eeg',
            'event_type': 'session_start',
            'payload': {},
        }]

        if NTP_CHECK_ENABLED:
            offset_s, delay_s = self._measure_ntp_offset()
            if offset_s is not None:
                self.ntp_offset_s = offset_s
                events.append({
                    'session_id': session_id,
                    'timestamp': time.time(),
                    'source': 'eeg',
                    'event_type': 'ntp_check',
                    'payload': {
                        'offset_s': offset_s,
                        'delay_s': delay_s,
                        'server': NTP_SERVER,
                    },
                })

        self.post_events_async(events, "Sessione aperta sul backend (con verifica NTP)")

    def _measure_ntp_offset(self):
        """
        Interroga il server NTP.

        Returns:
            tuple: (offset_s, delay_s), oppure (None, None) su fallimento
            (rete assente, UDP bloccato, ntplib non installato).
        """
        try:
            import ntplib
        except ImportError:
            print("[NTP] ntplib non installato: verifica saltata "
                  "(pip install ntplib)", flush=True)
            return None, None

        try:
            client = ntplib.NTPClient()
            # port=123 esplicito: la risoluzione del nome di servizio 'ntp'
            # non funziona su tutti i sistemi.
            response = client.request(
                NTP_SERVER, version=3, port=123, timeout=NTP_TIMEOUT_SECONDS)
            print(f"[NTP] scostamento orologio di sistema: {response.offset:+.3f}s "
                  f"(round-trip {response.delay:.3f}s, server {NTP_SERVER})", flush=True)
            return response.offset, response.delay

        except Exception as e:
            print(f"[NTP] verifica non riuscita ({type(e).__name__}: {e}), "
                  f"registrazione non influenzata", flush=True)
            return None, None

    def post_events_async(self, events, label, keep_path=None):
        """
        Invia una lista di eventi in un thread separato, senza restituire
        l'esito: variante fire and forget.

        Args:
            events (list): eventi nel formato condiviso con il plugin Moodle.
            label (str): descrizione mostrata nella label di stato.
            keep_path (str): file locale da citare in caso di errore.
        """
        if not UPLOAD_ENABLED:
            print(f"[POST] disabilitato (UPLOAD_ENABLED=False): {label}", flush=True)
            return

        if not events:
            print(f"[POST] nessun evento da inviare: {label}", flush=True)
            return

        thread = threading.Thread(
            target=self._post_worker,
            args=(events, label, keep_path),
            daemon=True,
        )
        thread.start()

    def _post_worker(self, events, label, keep_path=None):
        """
        Corpo della POST, fuori dal thread GUI. Non tocca widget: l'esito
        passa per upload_status_update.

        Returns:
            bool: True se il backend ha risposto positivamente. Serve
            all'upload incrementale, che avanza il cursore solo su successo.
        """
        suffix = f" - file conservato: {keep_path}" if keep_path else ""

        try:
            body = json.dumps(events).encode('utf-8')
            request = urllib.request.Request(
                BACKEND_URL,
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )

            with urllib.request.urlopen(request, timeout=BACKEND_TIMEOUT_SECONDS) as response:
                code = response.status
                reply = response.read().decode('utf-8', errors='replace')[:200]

            self.upload_status_update.emit(True, f"{label} ({len(events)} eventi, HTTP {code})")
            print(f"[POST] {label}: OK, {len(events)} eventi, HTTP {code}, risposta: {reply}", flush=True)
            return True

        except urllib.error.HTTPError as e:
            self.upload_status_update.emit(False, f"{label}: HTTP {e.code}{suffix}")
            print(f"[POST] {label}: errore HTTP {e.code} ({e.reason})", flush=True)
        except urllib.error.URLError as e:
            self.upload_status_update.emit(False, f"{label}: backend non raggiungibile{suffix}")
            print(f"[POST] {label}: backend non raggiungibile ({e.reason})", flush=True)
        except Exception as e:
            self.upload_status_update.emit(False, f"{label}: invio fallito{suffix}")
            print(f"[POST] {label}: errore inatteso {type(e).__name__}: {e}", flush=True)

        return False

    # ---------------------------------------------------------------- #
    #  Upload incrementale a chunk                                      #
    # ---------------------------------------------------------------- #

    def build_sample_event(self, ts_local, ts_idun, band_powers):
        """
        Costruisce l'evento 'sample' nell'envelope condivisa con il plugin
        Moodle. Unico punto in cui il formato e' definito: il fallback su CSV
        ricostruisce gli stessi campi rileggendo il file.

        Args:
            ts_local (float): orologio della macchina, riferimento per la
                sincronizzazione con Moodle.
            ts_idun (float): timestamp grezzo dell'SDK.
            band_powers (dict): potenze assolute per banda.
        """
        return {
            'session_id': self.session_id,
            'timestamp': ts_local,
            'source': 'eeg',
            'event_type': 'sample',
            'payload': {
                'timestamp_idun': ts_idun,
                'delta': band_powers['Delta'],
                'theta': band_powers['Theta'],
                'alpha': band_powers['Alpha'],
                'sigma': band_powers['Sigma'],
                'beta': band_powers['Beta'],
                'gamma': band_powers['Gamma'],
            },
        }

    def build_session_end_event(self, session_id, stop_ts):
        """
        Costruisce l'evento di chiusura sessione.

        Senza, il backend non sa che la registrazione e' finita: stopped_at e
        row_count restano NULL e ogni evento Moodle successivo continua a
        essere attribuito a quella sessione. session_id deve coincidere con
        quello di session_start.

        Args:
            session_id (str): chiave di correlazione della sessione.
            stop_ts (float): epoch in secondi dello Stop.
        """
        return {
            'session_id': session_id,
            'timestamp': stop_ts,
            'source': 'eeg',
            'event_type': 'session_end',
            # rows_local non serve al backend, che ricalcola row_count dal
            # database: e' il termine di paragone che rivela i campioni mai
            # arrivati.
            'payload': {'rows_local': self.recording_rows},
        }

    def maybe_flush_chunk(self):
        """
        Invia un chunk se la soglia e' stata raggiunta. Chiamata a ogni
        campione valido, cosi' il codice di acquisizione non conosce la
        cadenza. Con un chunk in volo i campioni si accumulano e partiranno
        con il successivo.
        """
        if self.upload_in_flight:
            return
        if len(self.pending_events) - self.upload_cursor >= UPLOAD_CHUNK_ROWS:
            self.flush_chunk()

    def flush_chunk(self):
        """
        Invia in un thread separato gli eventi non ancora confermati.

        Gira nel thread GUI, dove pending_events viene scritta: la fetta e'
        fissata qui e passata per valore al worker, che aggiorna solo
        upload_cursor e upload_in_flight. Da qui l'assenza di lock.
        """
        if not UPLOAD_ENABLED or self.upload_in_flight:
            return

        events = self.pending_events[self.upload_cursor:]
        if not events:
            return

        # Fissato adesso: i campioni che arrivano nel frattempo non devono
        # risultare inviati da questo chunk.
        new_cursor = self.upload_cursor + len(events)
        self.chunk_seq += 1
        self.upload_in_flight = True

        thread = threading.Thread(
            target=self._chunk_worker,
            args=(events, new_cursor, self.chunk_seq),
            daemon=True,
        )
        thread.start()

    def _chunk_worker(self, events, new_cursor, seq):
        """
        POST di un chunk periodico; avanza il cursore solo se ha successo.
        In caso di fallimento gli stessi eventi rientrano nella fetta del
        chunk successivo, senza rischio di duplicati.
        """
        try:
            ok = self._post_worker(events, f"Chunk {seq}", keep_path=self.bands_csv_path)
            if ok:
                self.upload_cursor = new_cursor
                print(f"[CHUNK] {seq}: {len(events)} eventi confermati, "
                      f"cursore a {new_cursor}", flush=True)
            else:
                print(f"[CHUNK] {seq}: invio non riuscito, {len(events)} eventi "
                      f"restano in coda per il prossimo chunk", flush=True)
        finally:
            # Anche su eccezione inattesa il flag va abbassato, altrimenti
            # nessun chunk ripartirebbe piu'.
            self.upload_in_flight = False

    def finalize_upload(self, path, session_id):
        """
        Chiude l'upload: chunk finale con session_end accodato e, se quello
        fallisce senza che nulla sia mai stato confermato, fallback sulla
        rilettura del CSV.

        Unico punto di decisione: tenere separati "invia il residuo" e
        "rileggi il CSV" sarebbe una corsa, perche' il chunk finale gira in
        un thread e la condizione sul cursore verrebbe valutata prima della
        sua risposta.

        Il fallback e' subordinato a upload_cursor == 0, altrimenti
        rispedirebbe campioni gia' accettati; in quel caso il recupero resta
        manuale dal CSV, che non viene mai cancellato.

        session_end viaggia sempre in coda ai campioni: il backend calcola
        row_count dopo aver inserito il lotto. Quando non c'e' alcun campione
        parte da solo, perche' una sessione non chiusa resta aperta a tempo
        indeterminato.

        Args:
            path (str): CSV della sessione appena chiusa.
            session_id (str): chiave di correlazione con gli eventi Moodle.
        """
        if not UPLOAD_ENABLED:
            print("[UPLOAD] disabilitato (UPLOAD_ENABLED=False), file mantenuto in locale", flush=True)
            return

        # La fine della sessione e' il momento dello Stop, non quello in cui
        # l'invio riesce.
        stop_ts = self.recording_stop_ts or time.time()
        session_end = self.build_session_end_event(session_id, stop_ts)

        if not path or self.recording_rows == 0:
            print("[UPLOAD] nessun campione da inviare, resta solo la chiusura "
                  "della sessione", flush=True)
            self.post_events_async([session_end], "Sessione chiusa sul backend")
            return

        events = self.pending_events[self.upload_cursor:]
        if not events:
            print(f"[UPLOAD] sessione gia' completa sul backend: "
                  f"{self.upload_cursor} campioni inviati a chunk", flush=True)
            self.post_events_async([session_end], "Sessione chiusa sul backend")
            return

        self.recording_status.setText(f"Invio finale... ({len(events)} campioni)")
        self.recording_status.setStyleSheet("font-size: 14px; color: #B08000;")

        self.chunk_seq += 1
        thread = threading.Thread(
            target=self._finalize_worker,
            args=(events, self.upload_cursor + len(events), self.chunk_seq,
                  path, session_id, session_end),
            daemon=True,
        )
        thread.start()

    def _finalize_worker(self, events, new_cursor, seq, path, session_id, session_end):
        """
        Chunk finale e, in caso di fallimento totale, fallback su CSV.

        session_end e' idempotente lato backend (chiave unica su session_id,
        source, event_type e timestamp), quindi puo' comparire in entrambi i
        tentativi senza duplicare nulla.
        """
        # Un chunk periodico puo' essere ancora in volo: attenderlo evita che
        # il suo esito sovrascriva il cursore appena aggiornato.
        deadline = time.time() + BACKEND_TIMEOUT_SECONDS
        while self.upload_in_flight and time.time() < deadline:
            time.sleep(0.05)

        self.upload_in_flight = True
        try:
            ok = self._post_worker(events + [session_end],
                                   f"Chunk {seq} (finale)", keep_path=path)
            if ok:
                self.upload_cursor = new_cursor
                print(f"[CHUNK] {seq}: {len(events)} eventi confermati (finale), "
                      f"sessione chiusa, cursore a {new_cursor}", flush=True)
                return

            if self.upload_cursor > 0:
                print(f"[UPLOAD] chunk finale non riuscito: {len(events)} "
                      f"campioni recuperabili da {path}", flush=True)
                # Dei due danni si sceglie il minore: row_count sottostimato
                # si riconosce dal confronto con rows_local, una sessione mai
                # chiusa continua ad attirare a se' gli eventi Moodle
                # successivi.
                self._post_worker([session_end], "Chiusura sessione", keep_path=path)
                return

            print("[UPLOAD] nessun chunk confermato in questa sessione, "
                  "fallback sulla rilettura del CSV", flush=True)
            self._upload_worker(path, session_id, session_end)
        finally:
            self.upload_in_flight = False

    def _upload_worker(self, path, session_id, session_end=None):
        """
        Rilegge il CSV e ricostruisce un evento per ogni campione. Il file
        non viene mai cancellato, cosi' un invio fallito resta recuperabile a
        mano.

        Args:
            path (str): CSV da rileggere.
            session_id (str): chiave di correlazione della sessione.
            session_end (dict): chiusura da accodare, None se gia' consegnata
                altrove.
        """
        try:
            events = []
            with open(path, newline="") as f:
                for row in csv.DictReader(f, delimiter=';'):
                    events.append({
                        'session_id': session_id,
                        'timestamp': float(row['timestamp_local']),
                        'source': 'eeg',
                        'event_type': 'sample',
                        'payload': {
                            'timestamp_idun': float(row['timestamp_idun']),
                            'delta': float(row['p_delta']),
                            'theta': float(row['p_theta']),
                            'alpha': float(row['p_alpha']),
                            'sigma': float(row['p_sigma']),
                            'beta': float(row['p_beta']),
                            'gamma': float(row['p_gamma']),
                        },
                    })
        except Exception as e:
            self.upload_status_update.emit(False, f"Lettura CSV fallita - file conservato: {path}")
            print(f"[UPLOAD] errore in lettura di {path}: {type(e).__name__}: {e}", flush=True)
            # CSV illeggibile: chiudere la sessione e' l'unica cosa ancora
            # possibile.
            if session_end is not None:
                self._post_worker([session_end], "Chiusura sessione", keep_path=path)
            return

        if session_end is not None:
            events.append(session_end)

        self._post_worker(events, "Inviata al backend", keep_path=path)

    def update_upload_visuals(self, success, message):
        """Riporta l'esito dell'upload nella label di stato (thread GUI)."""
        color = "#00AA00" if success else "#FF0000"
        self.recording_status.setText(message)
        self.recording_status.setStyleSheet(f"font-size: 14px; color: {color};")
