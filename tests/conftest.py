"""Gemeinsame Fixtures.

Die wichtigste Regel hier: **kein Test fasst die echte Meeting-DB an.**
``meeting_store`` leitet alle Pfade aus ``%APPDATA%`` ab und hält die
Verbindung in einer Modulvariablen — beides muss pro Test zurückgesetzt
werden, sonst schleppt der zweite Test die DB des ersten mit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Projekt-Root in den Pfad, damit `sidecar` und `core` importierbar sind,
# ohne das Paket zu installieren.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# --- Opt-in für teure Tests ------------------------------------------------
#
# Der Standardlauf muss in Sekunden durch sein, sonst läuft ihn niemand.
# Alles, was ein laufendes Ollama oder geladene ML-Modelle braucht, ist
# markiert und wird nur auf Zuruf mitgenommen.

_OPTIONAL = {
    "ollama": "braucht ein laufendes Ollama — mit --ollama einschalten",
    "slow": "lädt Modelle / dekodiert Audio — mit --slow einschalten",
}


def pytest_addoption(parser):
    for name, help_text in _OPTIONAL.items():
        parser.addoption(
            f"--{name}", action="store_true", default=False, help=help_text
        )


def pytest_collection_modifyitems(config, items):
    for name, reason in _OPTIONAL.items():
        if config.getoption(f"--{name}"):
            continue
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if name in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Frische, isolierte Meeting-DB. Gibt das ``meeting_store``-Modul zurück.

    DB und Meeting-Ordner sind je Test isoliert (APPDATA → tmp_path). Der
    **Modell-Cache** wird dagegen geteilt, wenn es ihn gibt: ohne das lädt
    jeder --slow-Lauf die Whisper-Gewichte (~3 GB) in ein
    Wegwerfverzeichnis — die 313 s der frühen Läufe waren zur Hälfte
    Download.
    """
    from sidecar import meeting_store

    real_appdata = os.environ.get("APPDATA")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    if real_appdata:
        real_models = Path(real_appdata) / "Blitztext" / "models"
        if real_models.is_dir():
            monkeypatch.setenv("BLITZTEXT_MODELS_DIR", str(real_models))
    meeting_store.close()  # eventuell offene Verbindung aus einem Vortest
    meeting_store.init_db()
    yield meeting_store
    meeting_store.close()


@pytest.fixture
def queue(store, tmp_path):
    """Warteschlange mit eigener Event-Sammlung, isoliert vom Singleton.

    Gibt ``(queue, events, audio)`` zurück. ``audio`` ist eine leere
    Platzhalterdatei — ``create_meeting_shell`` prüft nur die Existenz;
    Tests, die wirklich transkribieren, setzen ``run_stages`` ein.
    """
    from sidecar.jobs import JobQueue

    JobQueue.reset_for_tests()

    events: list[tuple[str, dict]] = []
    q = JobQueue(on_event=lambda name, payload: events.append((name, payload)))
    # Damit die RPC-Methoden dieselbe Instanz treffen wie der Test.
    JobQueue._instance = q

    audio = tmp_path / "probe.mp3"
    audio.write_bytes(b"nicht wirklich audio")

    yield q, events, audio

    q.stop()
    JobQueue.reset_for_tests()


@pytest.fixture
def sample_meeting(store):
    """Ein Meeting mit zwei Sprechern und zwei Turns, frisch persistiert.

    Baut den echten Weg nach: merge() → *_to_store_dict → upsert. Damit
    testen die aufsetzenden Tests dieselbe Datenform, die die Pipeline
    erzeugt, und nicht eine handgeschriebene Fantasie davon.
    """
    from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict

    words = [
        {"t0_ms": 0, "t1_ms": 500, "text": "Guten"},
        {"t0_ms": 500, "t1_ms": 1000, "text": "Morgen"},
        {"t0_ms": 3000, "t1_ms": 3500, "text": "Passt"},
        {"t0_ms": 3500, "t1_ms": 4000, "text": "mir"},
    ]
    segments = [
        {"start_ms": 0, "end_ms": 2000, "speaker": "SPEAKER_00"},
        {"start_ms": 2500, "end_ms": 4500, "speaker": "SPEAKER_01"},
    ]
    turns, speakers = merge(words, segments)

    meeting_id = store.create_meeting(
        title="Test-Meeting",
        language="de",
        whisper_model="large-v3",
        diar_model="pyannote/speaker-diarization-3.1",
        status="processing",
    )
    store.upsert_speakers(meeting_id, [speaker_to_store_dict(s) for s in speakers])
    refreshed = store.get_meeting(meeting_id)
    assert refreshed is not None
    label_to_id = {s["label"]: s["id"] for s in refreshed["speakers"]}
    store.upsert_turns(
        meeting_id, [turn_to_store_dict(t, label_to_id) for t in turns]
    )
    store.set_status(meeting_id, "ready")
    return meeting_id
