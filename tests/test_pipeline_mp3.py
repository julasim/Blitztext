"""MP3-Strecke: Dekodierung und die fünf Pipeline-Stages.

Nur mit ``--slow`` — hier werden echte Modelle geladen (Whisper, pyannote),
der Lauf dauert Minuten.

Der Test benutzt einen synthetischen Ton, kein Sprachmaterial: geprüft wird
die **Mechanik** (MP3 rein, alle Stages, Meeting landet auf `ready`), nicht
die Erkennungsqualität. Genau dort sitzen die Fehler, die beim Umbau der
Pipeline entstehen — und die MP3-Dekodierung läuft ohne librosa allein über
das PyAV, das faster-whisper mitbringt.
"""

from __future__ import annotations

import math
import wave

import pytest

pytestmark = pytest.mark.slow

SAMPLE_RATE = 16_000
DURATION_SEC = 3


def _write_wav(path, seconds: int = DURATION_SEC) -> None:
    frames = bytearray()
    for i in range(SAMPLE_RATE * seconds):
        # Leiser Sinus — laut genug zum Dekodieren, ohne Whisper zu reizen.
        value = int(3000 * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE))
        frames += value.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))


def _wav_to_mp3(src, dst) -> None:
    import av

    with av.open(str(src)) as inp, av.open(str(dst), "w") as out:
        ostream = out.add_stream("mp3", rate=44100)
        resampler = av.audio.resampler.AudioResampler(
            format=ostream.format, layout=ostream.layout, rate=ostream.rate
        )
        for frame in inp.decode(inp.streams.audio[0]):
            frame.pts = None
            for rframe in resampler.resample(frame):
                for packet in ostream.encode(rframe):
                    out.mux(packet)
        for packet in ostream.encode(None):
            out.mux(packet)


@pytest.fixture
def mp3(tmp_path):
    wav_path = tmp_path / "ton.wav"
    mp3_path = tmp_path / "ton.mp3"
    _write_wav(wav_path)
    _wav_to_mp3(wav_path, mp3_path)
    return mp3_path


def test_mp3_wird_zu_16khz_mono_dekodiert(mp3):
    """audio_io ohne librosa — PyAV kommt mit faster-whisper."""
    from sidecar.audio_io import load_audio

    audio, duration_ms = load_audio(str(mp3))

    assert audio.dtype.name == "float32"
    assert audio.ndim == 1, "muss Mono sein"
    # MP3 padded beim Kodieren leicht — Toleranz von 200 ms.
    assert abs(duration_ms - DURATION_SEC * 1000) < 200


def test_import_durchlaeuft_alle_stages(store, mp3):
    from sidecar.meeting_pipeline import run_import

    stages: list[str] = []

    def on_event(name: str, payload: dict) -> None:
        if name == "meeting.progress" and payload["stage"] not in stages:
            stages.append(payload["stage"])
        assert 0.0 <= payload.get("pct", 0) <= 1.0, "pct ist 0..1, nicht 0..100"

    meeting_id = run_import(str(mp3), title="Ton", language="de", on_event=on_event)

    assert stages == ["decode", "transcribe", "diarize", "merge", "persist"]

    m = store.get_meeting(meeting_id)
    assert m is not None
    assert m["status"] == "ready"
    assert m["duration_ms"] > 0


def test_quelldatei_landet_im_meeting_ordner(store, mp3):
    """Für Wiedergabe und Sprecher-Hörproben muss das Audio auffindbar bleiben."""
    from sidecar.meeting_pipeline import run_import

    meeting_id = run_import(str(mp3), title="Ton", language="de")

    m = store.get_meeting(meeting_id)
    assert m is not None
    from pathlib import Path

    audio_path = Path(m["audio_path"])
    assert audio_path.exists()
    assert audio_path.suffix == ".mp3"
    assert audio_path.parent == store.meeting_folder(meeting_id)


def test_fehlende_datei_meldet_sich_sauber(store, tmp_path):
    from sidecar.meeting_pipeline import create_meeting_shell

    with pytest.raises(FileNotFoundError):
        create_meeting_shell(str(tmp_path / "gibt-es-nicht.mp3"))


def test_zwei_dateien_durch_die_echte_warteschlange(store, mp3):
    """Der Integrationsbeweis: Queue-Worker + echte Pipeline, zwei Dateien
    nacheinander. Deckt ab, was die eingesetzten Tests in test_jobs.py
    bewusst aussparen — dass run_stages mit den Queue-Parametern wirklich
    zusammenspielt."""
    import time

    from sidecar.jobs import DONE, JobQueue
    from sidecar import jobs as jobs_mod

    JobQueue.reset_for_tests()
    events: list[tuple[str, dict]] = []
    q = JobQueue(on_event=lambda n, p: events.append((n, p)))
    JobQueue._instance = q
    try:
        first = q.enqueue(str(mp3), title="Erste")
        second = q.enqueue(str(mp3), title="Zweite")
        q.start()

        deadline = time.time() + 600
        while time.time() < deadline:
            states = [j["state"] for j in jobs_mod.list_jobs()]
            if all(s == DONE for s in states):
                break
            time.sleep(0.5)

        assert [j["state"] for j in jobs_mod.list_jobs()] == [DONE, DONE]
        for res in (first, second):
            m = store.get_meeting(res["meeting_id"])
            assert m is not None
            assert m["status"] == "ready"

        starts = [p["job_id"] for n, p in events if n == "queue.job_started"]
        assert starts == [first["job_id"], second["job_id"]], "Reihenfolge verletzt"
    finally:
        q.stop()
        JobQueue.reset_for_tests()
