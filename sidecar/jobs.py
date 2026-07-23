"""Import-Warteschlange — ein Job nach dem anderen.

Warum es sie gibt
-----------------
Vorher startete jeder ``meeting.import_file`` sofort einen eigenen
Daemon-Thread und vergaß ihn. Daraus folgten drei Dinge:

* **Kein Abbruch.** Ein versehentlich gestarteter Zwei-Stunden-Import ließ
  sich nur durch Abschießen der App stoppen.
* **Kein Wiederanlauf.** Das Meeting blieb dann für immer auf
  ``status="processing"`` stehen — niemand prüfte beim Start auf Waisen.
* **Kein Schutz vor Parallellauf.** Zwei gleichzeitige Importe teilen sich
  ``_transcriber_cache`` und die GPU.

Diese Datei löst alle drei: ein einziger Worker-Thread arbeitet die Jobs
seriell ab, der Zustand liegt in der DB (Tabelle ``jobs``, Migration 2) und
überlebt damit einen Absturz.

Zustände
--------
``queued`` → ``running`` → ``done`` | ``failed`` | ``cancelled``

Abbruch
-------
Ein wartender Job wird schlicht auf ``cancelled`` gesetzt und übersprungen.
Bei einem laufenden Job wird ein Flag gesetzt, das die Pipeline zwischen den
Stages und nach jedem Whisper-Segment prüft. **Während pyannote läuft gibt
es keinen Prüfpunkt** — dort meldet die Bibliothek keinen Fortschritt, der
Abbruch greift also erst, wenn die Diarization fertig ist. Bei langen
Dateien kann das dauern; ehrlicher als ein Abbruch-Knopf, der lügt.

Wiederanlauf
------------
Nur ein Prozess besitzt die DB. Steht beim Start ein Job auf ``running``,
kann das nur ein Absturz gewesen sein. Solche Jobs gehen zurück in die
Warteschlange — aber höchstens ``MAX_ATTEMPTS`` mal, sonst dreht eine Datei,
die den Prozess zuverlässig killt, eine Endlosschleife.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sidecar import meeting_store

_log = logging.getLogger("sidecar.jobs")

#: Wie oft ein nach einem Absturz gefundener Job neu versucht wird.
MAX_ATTEMPTS = 2

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

#: Zustände, die nichts mehr tun werden.
TERMINAL = (DONE, FAILED, CANCELLED)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Persistenz -------------------------------------------------------------
#
# Schema und Migrationen gehören meeting_store; die Job-Abfragen stehen hier,
# damit die Warteschlange in einer Datei nachvollziehbar bleibt.


def _row_to_job(row) -> dict:
    job = dict(row)
    job["params"] = json.loads(job.pop("params_json") or "{}")
    return job


def get_job(job_id: str) -> dict | None:
    row = meeting_store.connection().execute(
        "SELECT * FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return _row_to_job(row) if row is not None else None


def list_jobs(limit: int = 200, states: tuple[str, ...] | None = None) -> list[dict]:
    """Warteschlange in Abarbeitungsreihenfolge."""
    conn = meeting_store.connection()
    if states:
        marks = ",".join("?" for _ in states)
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE state IN ({marks}) ORDER BY position LIMIT ?",
            (*states, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY position LIMIT ?", (int(limit),)
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def _next_position(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM jobs").fetchone()
    return int(row["p"])


def _set_state(job_id: str, state: str, **fields: Any) -> None:
    sets = ["state = ?"]
    values: list[Any] = [state]
    for key, value in fields.items():
        sets.append(f"{key} = ?")
        values.append(value)
    values.append(job_id)
    meeting_store.connection().execute(
        f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", values
    )


# --- Warteschlange ----------------------------------------------------------


class JobQueue:
    """Singleton. ``start()`` einmal beim Sidecar-Start aufrufen."""

    _instance: "JobQueue | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, on_event: Callable[[str, dict], None] | None = None) -> None:
        self._on_event = on_event
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._stopping = False
        self._current: str | None = None
        self._cancel_requested: set[str] = set()

    @classmethod
    def instance(cls) -> "JobQueue":
        with cls._instance_lock:
            if cls._instance is None:
                from sidecar.rpc import emit_event

                cls._instance = cls(on_event=emit_event)
            return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Singleton fallen lassen — Tests bekommen sonst den Worker des
        vorherigen Tests samt dessen (gelöschter) DB."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.stop()
            cls._instance = None

    # -- Lebenszyklus --------------------------------------------------

    def start(self) -> dict:
        """Waisen einsammeln und den Worker starten. Idempotent."""
        meeting_store.init_db()
        recovered = self.recover_orphans()
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return recovered
            self._stopping = False
            self._worker = threading.Thread(
                target=self._loop, name="job-queue", daemon=True
            )
            self._worker.start()
        self._wake.set()
        return recovered

    def stop(self) -> None:
        """Worker nach dem laufenden Job beenden. Für Tests und Shutdown."""
        with self._lock:
            self._stopping = True
            worker = self._worker
        self._wake.set()
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        with self._lock:
            self._worker = None

    def recover_orphans(self) -> dict:
        """``running``-Jobs beim Start können nur ein Absturz sein."""
        requeued: list[str] = []
        failed: list[str] = []
        for job in list_jobs(states=(RUNNING,)):
            attempts = int(job["attempts"])
            if attempts < MAX_ATTEMPTS:
                _set_state(job["id"], QUEUED, started_at=None)
                requeued.append(job["id"])
                _log.warning(
                    "Job %s war unterbrochen (Versuch %d/%d) — zurück in die Warteschlange",
                    job["id"][:8], attempts, MAX_ATTEMPTS,
                )
            else:
                self._fail(
                    job,
                    f"Nach {attempts} Versuchen abgebrochen — die Datei bringt "
                    f"den Import reproduzierbar zum Absturz.",
                )
                failed.append(job["id"])
        if requeued or failed:
            self._emit("queue.recovered", {"requeued": requeued, "failed": failed})
        return {"requeued": len(requeued), "failed": len(failed)}

    # -- Öffentliche Operationen ---------------------------------------

    def enqueue(
        self,
        path: str,
        *,
        title: str | None = None,
        language: str = "de",
        whisper_model: str | None = None,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
    ) -> dict:
        """Datei einreihen. Legt die Meeting-Hülle sofort an, damit die UI
        eine ``meeting_id`` bekommt, und gibt sofort zurück."""
        from sidecar.meeting_pipeline import create_meeting_shell

        meeting_id, resolved_model = create_meeting_shell(
            path, title=title, language=language, whisper_model=whisper_model
        )

        job_id = str(uuid.uuid4())
        params = {
            "language": language,
            "whisper_model": resolved_model,
            "min_speakers": min_speakers,
            "max_speakers": max_speakers,
        }
        conn = meeting_store.connection()
        conn.execute(
            "INSERT INTO jobs (id, meeting_id, source_path, params_json, state, "
            " position, attempts, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (
                job_id,
                meeting_id,
                str(path),
                json.dumps(params, ensure_ascii=False),
                QUEUED,
                _next_position(conn),
                _now(),
            ),
        )

        _log.info("Job %s eingereiht: %s", job_id[:8], path)
        self._emit(
            "queue.enqueued",
            {"job_id": job_id, "meeting_id": meeting_id, "path": str(path)},
        )
        self._emit_changed()
        self._wake.set()
        return {"job_id": job_id, "meeting_id": meeting_id}

    def cancel(self, job_id: str) -> dict:
        """Wartenden Job verwerfen oder laufenden zum Abbruch vormerken."""
        job = get_job(job_id)
        if job is None:
            return {"ok": False, "reason": "unbekannter Job"}
        if job["state"] in TERMINAL:
            return {"ok": False, "reason": f"Job ist bereits {job['state']}", "state": job["state"]}

        if job["state"] == RUNNING:
            with self._lock:
                self._cancel_requested.add(job_id)
            _log.info("Abbruch für laufenden Job %s vorgemerkt", job_id[:8])
            return {"ok": True, "state": RUNNING, "pending": True}

        self._cancel_job_row(job)
        self._emit_changed()
        return {"ok": True, "state": CANCELLED, "pending": False}

    def state(self) -> dict:
        counts = {s: 0 for s in (QUEUED, RUNNING, DONE, FAILED, CANCELLED)}
        for row in meeting_store.connection().execute(
            "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
        ):
            counts[row["state"]] = int(row["n"])
        with self._lock:
            current = self._current
            alive = self._worker is not None and self._worker.is_alive()
        return {"counts": counts, "current_job_id": current, "worker_alive": alive}

    def clear_finished(self) -> dict:
        """Erledigte, fehlgeschlagene und abgebrochene Einträge entfernen."""
        conn = meeting_store.connection()
        cur = conn.execute(
            "DELETE FROM jobs WHERE state IN (?, ?, ?)", TERMINAL
        )
        self._emit_changed()
        return {"ok": True, "removed": cur.rowcount}

    # -- Worker ---------------------------------------------------------

    def _loop(self) -> None:
        _log.info("Job-Worker gestartet")
        while True:
            with self._lock:
                if self._stopping:
                    break
            job = self._claim_next()
            if job is None:
                # Nichts zu tun — schlafen, bis enqueue() weckt.
                self._wake.wait(timeout=30)
                self._wake.clear()
                continue
            try:
                self._run(job)
            except Exception:
                # _run behandelt seine Fehler selbst; hier landet nur, was
                # beim Aufräumen schiefging. Der Worker darf daran nicht
                # sterben, sonst steht die Warteschlange still.
                _log.exception("Job-Worker: unerwarteter Fehler bei %s", job["id"][:8])
        _log.info("Job-Worker beendet")

    def _claim_next(self) -> dict | None:
        conn = meeting_store.connection()
        row = conn.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY position LIMIT 1", (QUEUED,)
        ).fetchone()
        if row is None:
            return None
        job = _row_to_job(row)
        conn.execute(
            "UPDATE jobs SET state = ?, started_at = ?, attempts = attempts + 1 "
            "WHERE id = ?",
            (RUNNING, _now(), job["id"]),
        )
        with self._lock:
            self._current = job["id"]
        return job

    def _run(self, job: dict) -> None:
        from sidecar.meeting_pipeline import PipelineCancelled, run_stages

        job_id = job["id"]
        meeting_id = job["meeting_id"]
        params = job["params"]

        with self._lock:
            cancelled_before_start = job_id in self._cancel_requested
        if cancelled_before_start:
            self._cancel_job_row(get_job(job_id) or job)
            self._finish_current()
            return

        self._emit(
            "queue.job_started",
            {"job_id": job_id, "meeting_id": meeting_id, "path": job["source_path"]},
        )
        self._emit_changed()

        def should_cancel() -> bool:
            with self._lock:
                return job_id in self._cancel_requested

        try:
            run_stages(
                meeting_id,
                job["source_path"],
                language=params.get("language", "de"),
                whisper_model=params["whisper_model"],
                min_speakers=params.get("min_speakers"),
                max_speakers=params.get("max_speakers"),
                on_event=self._on_event,
                should_cancel=should_cancel,
            )
        except PipelineCancelled:
            _log.info("Job %s abgebrochen", job_id[:8])
            self._cancel_job_row(get_job(job_id) or job)
        except Exception as e:  # noqa: BLE001 — jeder Fehler landet am Job
            _log.exception("Job %s fehlgeschlagen", job_id[:8])
            self._fail(get_job(job_id) or job, str(e))
        else:
            _set_state(job_id, DONE, finished_at=_now(), error=None)
            self._emit("queue.job_done", {"job_id": job_id, "meeting_id": meeting_id})
        finally:
            with self._lock:
                self._cancel_requested.discard(job_id)
            self._finish_current()

    def _finish_current(self) -> None:
        with self._lock:
            self._current = None
        self._emit_changed()

    # -- Zustandsübergänge ----------------------------------------------

    def _cancel_job_row(self, job: dict) -> None:
        """Job auf ``cancelled`` setzen und die leere Meeting-Hülle entfernen.

        Der Job-Eintrag überlebt das Löschen, weil ``jobs.meeting_id`` auf
        ``ON DELETE SET NULL`` steht — die Warteschlange behält also ihre
        Historie, die Bibliothek bekommt kein leeres Meeting.
        """
        meeting_id = job.get("meeting_id")
        _set_state(job["id"], CANCELLED, finished_at=_now())
        if meeting_id:
            meeting_store.delete_meeting(meeting_id)
        self._emit(
            "queue.job_cancelled",
            {"job_id": job["id"], "meeting_id": meeting_id},
        )

    def _fail(self, job: dict, message: str) -> None:
        _set_state(job["id"], FAILED, finished_at=_now(), error=message[:2000])
        meeting_id = job.get("meeting_id")
        if meeting_id:
            meeting_store.set_status(meeting_id, "error")
        self._emit(
            "queue.job_failed",
            {"job_id": job["id"], "meeting_id": meeting_id, "message": message},
        )

    # -- Events ----------------------------------------------------------

    def _emit(self, name: str, payload: dict) -> None:
        if self._on_event is not None:
            try:
                self._on_event(name, payload)
            except Exception:  # noqa: BLE001 — ein kaputter Kanal darf die
                _log.exception("Event %s konnte nicht gesendet werden", name)

    def _emit_changed(self) -> None:
        self._emit("queue.changed", self.state())
