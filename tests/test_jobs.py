"""Warteschlange: serielle Abarbeitung, Abbruch, Wiederanlauf.

Nebenläufigkeit prüft man nicht per Augenschein — deshalb laufen diese
Tests gegen eine **eingesetzte Pipeline** (Monkeypatch auf ``run_stages``),
nicht gegen Whisper. Getestet wird die Queue-Mechanik: Reihenfolge,
Zustandsübergänge, Abbruch an einem Prüfpunkt, Waisen nach einem Absturz.
"""

from __future__ import annotations

import threading
import time

import pytest

from sidecar import jobs
from sidecar.jobs import CANCELLED, DONE, FAILED, QUEUED, RUNNING, JobQueue


def _fake_stages(record: list[str], *, fail: str | None = None, block: threading.Event | None = None):
    """Ersetzt run_stages: notiert die Meeting-ID, respektiert should_cancel."""

    def _run(meeting_id, file_path, *, should_cancel=None, **kwargs):
        from sidecar.meeting_pipeline import PipelineCancelled

        if block is not None:
            # Simuliert einen langen Lauf mit Prüfpunkten, wie ihn Whisper
            # zwischen den Segmenten hat.
            while not block.is_set():
                if should_cancel is not None and should_cancel():
                    raise PipelineCancelled()
                time.sleep(0.01)
        if should_cancel is not None and should_cancel():
            raise PipelineCancelled()
        if fail is not None:
            raise RuntimeError(fail)
        record.append(meeting_id)

    return _run


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --- Reihenfolge ------------------------------------------------------------


def test_jobs_laufen_seriell_in_einreihungsreihenfolge(queue, monkeypatch, store):
    q, events, audio = queue
    done: list[str] = []
    monkeypatch.setattr("sidecar.meeting_pipeline.run_stages", _fake_stages(done))

    ids = [q.enqueue(str(audio), title=f"Datei {i}")["meeting_id"] for i in range(3)]
    q.start()

    assert _wait_until(lambda: len(done) == 3), f"nur {len(done)} von 3 erledigt"
    assert done == ids, "FIFO verletzt"
    assert all(j["state"] == DONE for j in jobs.list_jobs())


def test_position_steigt_monoton(queue, store):
    q, _events, audio = queue

    q.enqueue(str(audio))
    q.enqueue(str(audio))
    q.enqueue(str(audio))

    positions = [j["position"] for j in jobs.list_jobs()]
    assert positions == sorted(positions)
    assert len(set(positions)) == 3, "Positionen müssen eindeutig sein"


def test_enqueue_legt_meeting_huelle_an(queue, store):
    q, _events, audio = queue

    res = q.enqueue(str(audio), title="Wichtig")

    m = store.get_meeting(res["meeting_id"])
    assert m is not None
    assert m["title"] == "Wichtig"
    assert m["status"] == "processing"


def test_fehlende_datei_wird_nicht_eingereiht(queue, store, tmp_path):
    q, _events, _audio = queue

    with pytest.raises(FileNotFoundError):
        q.enqueue(str(tmp_path / "gibt-es-nicht.mp3"))

    assert jobs.list_jobs() == []


# --- Fehler -----------------------------------------------------------------


def test_fehlgeschlagener_job_stoppt_die_schlange_nicht(queue, monkeypatch, store):
    """Bei 50 Dateien darf eine kaputte nicht die restlichen 49 blockieren."""
    q, events, audio = queue
    monkeypatch.setattr(
        "sidecar.meeting_pipeline.run_stages", _fake_stages([], fail="kaputte Datei")
    )

    first = q.enqueue(str(audio))["job_id"]
    second = q.enqueue(str(audio))["job_id"]
    q.start()

    assert _wait_until(
        lambda: all(j["state"] == FAILED for j in jobs.list_jobs())
    ), [j["state"] for j in jobs.list_jobs()]

    by_id = {j["id"]: j for j in jobs.list_jobs()}
    assert "kaputte Datei" in by_id[first]["error"]
    assert by_id[second]["state"] == FAILED, "zweiter Job wurde übersprungen"


def test_fehler_setzt_das_meeting_auf_error(queue, monkeypatch, store):
    q, _events, audio = queue
    monkeypatch.setattr(
        "sidecar.meeting_pipeline.run_stages", _fake_stages([], fail="Pech")
    )

    meeting_id = q.enqueue(str(audio))["meeting_id"]
    q.start()

    assert _wait_until(lambda: store.get_meeting(meeting_id)["status"] == "error")


# --- Abbruch ----------------------------------------------------------------


def test_wartender_job_wird_verworfen(queue, store):
    q, _events, audio = queue
    res = q.enqueue(str(audio))

    out = q.cancel(res["job_id"])

    assert out["ok"] is True
    assert out["pending"] is False
    job = jobs.get_job(res["job_id"])
    assert job["state"] == CANCELLED
    # Die leere Hülle verschwindet, der Job-Eintrag bleibt als Historie.
    assert store.get_meeting(res["meeting_id"]) is None
    assert job["meeting_id"] is None


def test_laufender_job_bricht_am_pruefpunkt_ab(queue, monkeypatch, store):
    q, _events, audio = queue
    block = threading.Event()
    monkeypatch.setattr(
        "sidecar.meeting_pipeline.run_stages", _fake_stages([], block=block)
    )

    res = q.enqueue(str(audio))
    q.start()
    assert _wait_until(lambda: jobs.get_job(res["job_id"])["state"] == RUNNING)

    out = q.cancel(res["job_id"])

    assert out["pending"] is True, "laufender Job kann nicht sofort weg sein"
    assert _wait_until(lambda: jobs.get_job(res["job_id"])["state"] == CANCELLED)
    block.set()


def test_abbruch_laesst_folgejob_weiterlaufen(queue, monkeypatch, store):
    q, _events, audio = queue
    done: list[str] = []
    monkeypatch.setattr("sidecar.meeting_pipeline.run_stages", _fake_stages(done))

    first = q.enqueue(str(audio))
    second = q.enqueue(str(audio))
    q.cancel(first["job_id"])
    q.start()

    assert _wait_until(lambda: done == [second["meeting_id"]])
    assert jobs.get_job(first["job_id"])["state"] == CANCELLED
    assert jobs.get_job(second["job_id"])["state"] == DONE


def test_abbruch_eines_erledigten_jobs_meldet_sich(queue, monkeypatch, store):
    q, _events, audio = queue
    monkeypatch.setattr("sidecar.meeting_pipeline.run_stages", _fake_stages([]))
    res = q.enqueue(str(audio))
    q.start()
    assert _wait_until(lambda: jobs.get_job(res["job_id"])["state"] == DONE)

    out = q.cancel(res["job_id"])

    assert out["ok"] is False
    assert out["state"] == DONE


def test_abbruch_unbekannter_job(queue, store):
    q, _events, _audio = queue

    assert q.cancel("gibt-es-nicht")["ok"] is False


# --- Wiederanlauf nach Absturz ---------------------------------------------


def test_running_job_geht_nach_absturz_zurueck_in_die_schlange(queue, store):
    """Nur ein Prozess besitzt die DB — ein `running`-Job beim Start kann
    nur bedeuten, dass der letzte Lauf abgestürzt ist."""
    q, _events, audio = queue
    res = q.enqueue(str(audio))
    # Absturz mitten im Lauf nachstellen.
    jobs._set_state(res["job_id"], RUNNING, attempts=1)

    out = q.recover_orphans()

    assert out == {"requeued": 1, "failed": 0}
    assert jobs.get_job(res["job_id"])["state"] == QUEUED


def test_wiederholt_abstuerzende_datei_wird_aufgegeben(queue, store):
    """Sonst dreht eine Datei, die den Prozess zuverlässig killt, eine
    Endlosschleife über alle Neustarts."""
    q, _events, audio = queue
    res = q.enqueue(str(audio))
    jobs._set_state(res["job_id"], RUNNING, attempts=jobs.MAX_ATTEMPTS)

    out = q.recover_orphans()

    assert out == {"requeued": 0, "failed": 1}
    job = jobs.get_job(res["job_id"])
    assert job["state"] == FAILED
    assert "Versuche" in job["error"]
    assert store.get_meeting(res["meeting_id"])["status"] == "error"


def test_recover_laesst_wartende_und_fertige_in_ruhe(queue, monkeypatch, store):
    q, _events, audio = queue
    wartend = q.enqueue(str(audio))["job_id"]
    fertig = q.enqueue(str(audio))["job_id"]
    jobs._set_state(fertig, DONE)

    q.recover_orphans()

    assert jobs.get_job(wartend)["state"] == QUEUED
    assert jobs.get_job(fertig)["state"] == DONE


# --- Zustand und Aufräumen --------------------------------------------------


def test_state_zaehlt_je_zustand(queue, store):
    q, _events, audio = queue
    a = q.enqueue(str(audio))["job_id"]
    q.enqueue(str(audio))
    jobs._set_state(a, DONE)

    counts = q.state()["counts"]

    assert counts[QUEUED] == 1
    assert counts[DONE] == 1


def test_clear_finished_raeumt_nur_abgeschlossenes(queue, store):
    q, _events, audio = queue
    wartend = q.enqueue(str(audio))["job_id"]
    fertig = q.enqueue(str(audio))["job_id"]
    jobs._set_state(fertig, DONE)

    out = q.clear_finished()

    assert out["removed"] == 1
    assert [j["id"] for j in jobs.list_jobs()] == [wartend]


# --- RPC: Stapel einreihen --------------------------------------------------


def test_queue_enqueue_nimmt_ordner_und_meldet_uebersprungenes(queue, store, tmp_path):
    """Der Weg, den der Ordner-Drop im UI nehmen wird."""
    import sidecar.methods  # noqa: F401 — registriert die Handler
    from sidecar.rpc import call_method

    q, _events, _audio = queue
    ordner = tmp_path / "stapel"
    ordner.mkdir()
    (ordner / "a.mp3").write_bytes(b"x")
    (ordner / "b.wav").write_bytes(b"x")
    (ordner / "liesmich.txt").write_bytes(b"x")

    res = call_method(
        "queue.enqueue", {"paths": [str(ordner), str(tmp_path / "fehlt.mp3")]}
    )

    assert res["count"] == 2
    assert [j["path"].endswith("a.mp3") for j in res["enqueued"]][0] is True
    assert any(s["reason"] == "nicht gefunden" for s in res["skipped"])
    assert [j["state"] for j in jobs.list_jobs()] == [QUEUED, QUEUED]


def test_config_get_liefert_die_endungsliste(store):
    """Damit der Dateidialog im Frontend keine eigene Liste pflegt."""
    import sidecar.methods  # noqa: F401
    from sidecar.rpc import call_method

    cfg = call_method("config.get")

    assert ".mp3" in cfg["audio_extensions"]


def test_events_melden_start_und_ende(queue, monkeypatch, store):
    q, events, audio = queue
    monkeypatch.setattr("sidecar.meeting_pipeline.run_stages", _fake_stages([]))

    q.enqueue(str(audio))
    q.start()
    assert _wait_until(lambda: any(n == "queue.job_done" for n, _ in events))

    namen = [n for n, _ in events]
    assert "queue.enqueued" in namen
    assert "queue.job_started" in namen
    assert "queue.job_done" in namen
