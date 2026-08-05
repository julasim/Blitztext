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

    # Nur die betroffenen Zähler prüfen — das Ergebnis darf um weitere
    # Schlüssel wachsen, ohne dass dieser Test bricht.
    assert (out["requeued"], out["failed"]) == (1, 0)
    assert jobs.get_job(res["job_id"])["state"] == QUEUED


def test_wiederholt_abstuerzende_datei_wird_aufgegeben(queue, store):
    """Sonst dreht eine Datei, die den Prozess zuverlässig killt, eine
    Endlosschleife über alle Neustarts."""
    q, _events, audio = queue
    res = q.enqueue(str(audio))
    jobs._set_state(res["job_id"], RUNNING, attempts=jobs.MAX_ATTEMPTS)

    out = q.recover_orphans()

    assert (out["requeued"], out["failed"]) == (0, 1)
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


def test_queue_enqueue_nimmt_ordner_und_meldet_uebersprungenes(
    queue, store, tmp_path, monkeypatch
):
    """Der Weg, den der Ordner-Drop im UI nimmt."""
    import sidecar.methods  # noqa: F401 — registriert die Handler
    from sidecar.rpc import call_method

    q, _events, _audio = queue
    # `queue.enqueue` startet den Worker, falls er nicht läuft — sonst
    # sammelten sich Jobs an, die niemand abarbeitet. Für diesen Test wird
    # die Pipeline deshalb eingesetzt; die Platzhalterdateien hier sind
    # kein echtes Audio.
    verarbeitet: list[str] = []
    monkeypatch.setattr(
        "sidecar.meeting_pipeline.run_stages", _fake_stages(verarbeitet)
    )

    ordner = tmp_path / "stapel"
    ordner.mkdir()
    (ordner / "a.mp3").write_bytes(b"x")
    (ordner / "b.wav").write_bytes(b"x")
    (ordner / "liesmich.txt").write_bytes(b"x")

    res = call_method(
        "queue.enqueue", {"paths": [str(ordner), str(tmp_path / "fehlt.mp3")]}
    )

    assert res["count"] == 2
    assert res["enqueued"][0]["path"].endswith("a.mp3")
    assert any(s["reason"] == "nicht gefunden" for s in res["skipped"])
    # Beide Dateien sind eingereiht — in welchem Zustand sie gerade stehen,
    # hängt davon ab, wie weit der Worker schon ist.
    assert len(jobs.list_jobs()) == 2
    assert _wait_until(
        lambda: all(j["state"] == DONE for j in jobs.list_jobs())
    ), "der Worker muss die Warteschlange auch wirklich abarbeiten"


def test_config_get_liefert_die_endungsliste(store):
    """Damit der Dateidialog im Frontend keine eigene Liste pflegt."""
    import sidecar.methods  # noqa: F401
    from sidecar.rpc import call_method

    cfg = call_method("config.get")

    assert ".mp3" in cfg["audio_extensions"]


def test_wiederanlauf_raeumt_meetings_ohne_job(queue, store):
    """Meeting-Hülle ohne Job — der Absturz zwischen zwei Schreibvorgängen.

    `create_meeting_shell` committet die Hülle, danach erst wird die Job-Zeile
    geschrieben. Stirbt der Prozess dazwischen, blieb ein Meeting für immer
    auf „wird verarbeitet" stehen: `recover_orphans` schaute nur auf Jobs im
    Zustand `running` und bekam solche Waisen nie zu sehen.
    """
    q, _events, _audio = queue

    leer = store.create_meeting(title="Absturz vor der Job-Zeile", status="processing")
    mit_inhalt = store.create_meeting(title="Absturz im persist", status="processing")
    store.upsert_speakers(mit_inhalt, [{"label": "Speaker 1"}])
    sprecher_id = store.get_meeting(mit_inhalt)["speakers"][0]["id"]
    store.upsert_turns(
        mit_inhalt,
        [{"speaker_id": sprecher_id, "idx": 0, "start_ms": 0, "end_ms": 900,
          "text_raw": "Halb fertig."}],
    )

    ergebnis = q.recover_orphans()

    assert ergebnis["orphaned_meetings"] == 2
    assert store.get_meeting(leer) is None, "leere Hülle muss weg"
    uebrig = store.get_meeting(mit_inhalt)
    assert uebrig is not None, "Teilarbeit darf nicht verschwinden"
    assert uebrig["status"] == "error"


def test_wiederanlauf_laesst_meetings_mit_offenem_job_in_ruhe(queue, store):
    """Gegenprobe: wer noch einen wartenden Job hat, wird nicht angefasst."""
    q, _events, audio = queue

    res = q.enqueue(str(audio))
    meeting_id = res["meeting_id"]

    q.recover_orphans()

    m = store.get_meeting(meeting_id)
    assert m is not None
    assert m["status"] == "processing"


def test_shutdown_gibt_laufenden_job_frei_ohne_versuch_zu_verbrauchen(
    queue, monkeypatch, store
):
    """Die App zu schließen ist kein Absturz.

    Vorher endete der Sidecar ohne die Warteschlange anzuhalten: der laufende
    Job blieb auf ``running``, und der nächste Start wertete das als Absturz
    und verbrauchte einen der zwei Versuche. Wer eine lange Datei importierte
    und zweimal dazwischen die App schloss, bekam sie endgültig als „bringt
    den Import reproduzierbar zum Absturz" abgestempelt — sachlich falsch.
    """
    q, _events, audio = queue
    laeuft = threading.Event()
    monkeypatch.setattr(
        "sidecar.meeting_pipeline.run_stages", _fake_stages([], block=laeuft)
    )

    job_id = q.enqueue(str(audio))["job_id"]
    q.start()
    assert _wait_until(lambda: jobs.get_job(job_id)["state"] == RUNNING)
    assert jobs.get_job(job_id)["attempts"] == 1

    q.shutdown()  # Fenster zu, während der Import läuft

    job = jobs.get_job(job_id)
    assert job["state"] == QUEUED, "muss zurück in die Warteschlange"
    assert job["attempts"] == 0, "das Schließen darf keinen Versuch kosten"
    assert job["started_at"] is None
    laeuft.set()


def test_stop_vergisst_lebenden_worker_nicht(queue):
    """``stop()`` setzte ``_worker = None`` auch bei überschrittenem Timeout.

    Ein folgendes ``start()`` legte dann einen ZWEITEN Worker an — beide
    hätten parallel Jobs übernommen, also genau der Parallellauf, den die
    Warteschlange verhindern soll.

    Geprüft wird gegen einen Platzhalter statt gegen einen echten Thread:
    ein wirklich hängender Worker müsste den 5-Sekunden-Timeout aussitzen
    und die DB unter der Fixture wegziehen.
    """
    q, _events, _audio = queue

    class HaengenderWorker:
        def is_alive(self) -> bool:
            return True

        def join(self, timeout=None) -> None:
            return None  # läuft in den Timeout, ohne zu enden

    haengt = HaengenderWorker()
    q._worker = haengt  # type: ignore[assignment]

    q.stop()

    assert q._worker is haengt, "lebenden Worker nicht vergessen"
    q._worker = None  # Fixture-Teardown nicht mit dem Platzhalter belasten


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
