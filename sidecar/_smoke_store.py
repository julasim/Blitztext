"""Integrations-Smoke: merger → meeting_store → get_meeting.

Zeigt, dass die Datenflüsse zwischen den Modulen sauber passen, ohne
pyannote oder Whisper auszuführen. Nutzt einen temporären APPDATA-Pfad
damit die echte Meeting-DB unberührt bleibt.

Run: python -m sidecar._smoke_store
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    # Isolierte APPDATA-Umgebung: keine Kollision mit Produktion.
    tmp = tempfile.mkdtemp(prefix="blitztext-smoke-")
    os.environ["APPDATA"] = tmp
    print(f"APPDATA isoliert: {tmp}")

    # Erst JETZT die Module importieren — sie lesen APPDATA beim ersten Call.
    from sidecar import meeting_store as store
    from sidecar.merger import (
        merge,
        speaker_to_store_dict,
        turn_to_store_dict,
    )

    store.init_db()
    print(f"DB angelegt: {store.db_path()}")

    # --- 1) Fake Whisper-Wörter + pyannote-Segmente ---
    words = [
        {"t0_ms": 0, "t1_ms": 500, "text": "Hallo"},
        {"t0_ms": 500, "t1_ms": 1000, "text": "zusammen"},
        {"t0_ms": 1000, "t1_ms": 1500, "text": "heute"},
        {"t0_ms": 1500, "t1_ms": 2000, "text": "ÖNORM"},
        {"t0_ms": 3000, "t1_ms": 3500, "text": "Passt"},
        {"t0_ms": 3500, "t1_ms": 4000, "text": "mir"},
        {"t0_ms": 4000, "t1_ms": 4500, "text": "auch"},
    ]
    segs = [
        {"start_ms": 0, "end_ms": 2200, "speaker": "SPEAKER_00"},
        {"start_ms": 2800, "end_ms": 4800, "speaker": "SPEAKER_01"},
    ]

    turns, speakers = merge(words, segs)
    assert len(turns) == 2, f"expected 2 turns, got {len(turns)}"
    assert len(speakers) == 2
    print(f"Merger: {len(turns)} turns, {len(speakers)} speakers")

    # --- 2) Meeting in Store anlegen, Speakers + Turns schreiben ---
    mid = store.create_meeting(
        title="Bauberatung Projekt Luisa",
        audio_path="(synthetic)",
        duration_ms=4500,
        language="de",
        whisper_model="large-v3-turbo",
        diar_model="pyannote/speaker-diarization-3.1",
        status="ready",
    )
    print(f"Meeting id: {mid}")

    # Speaker-Dicts erst persistieren (damit IDs entstehen)
    speaker_dicts = [speaker_to_store_dict(s) for s in speakers]
    store.upsert_speakers(mid, speaker_dicts)

    # Zurücklesen um die IDs zu bekommen — wir brauchen label → id Mapping
    persisted = store.get_meeting(mid)
    assert persisted is not None
    speaker_id_by_label = {s["label"]: s["id"] for s in persisted["speakers"]}
    print(f"Speaker-IDs: {speaker_id_by_label}")

    # Turns mit den echten speaker_ids schreiben
    turn_dicts = [turn_to_store_dict(t, speaker_id_by_label) for t in turns]
    store.upsert_turns(mid, turn_dicts)

    # --- 3) Voller Round-Trip: get_meeting und verifizieren ---
    m = store.get_meeting(mid)
    assert m is not None
    assert m["title"] == "Bauberatung Projekt Luisa"
    assert m["status"] == "ready"
    assert len(m["speakers"]) == 2
    assert len(m["turns"]) == 2

    t0 = m["turns"][0]
    assert t0["idx"] == 0
    assert t0["text_raw"].startswith("Hallo zusammen")
    assert "ÖNORM" in t0["text_raw"]
    assert len(t0["words"]) == 4
    assert t0["speaker_id"] in speaker_id_by_label.values()
    print(
        f"Turn 0: '{t0['text_raw']}' "
        f"({t0['start_ms']}-{t0['end_ms']}ms, {len(t0['words'])} words, "
        f"overlap={t0['overlap_flag']})"
    )

    t1 = m["turns"][1]
    assert t1["text_raw"] == "Passt mir auch"
    assert t1["speaker_id"] != t0["speaker_id"]
    print(f"Turn 1: '{t1['text_raw']}' (speaker wechselt: ok)")

    # --- 4) Rename-Speaker ---
    first_speaker_id = speaker_id_by_label["Speaker 1"]
    ok = store.rename_speaker(mid, first_speaker_id, "Julius")
    assert ok
    m2 = store.get_meeting(mid)
    assert m2 is not None
    names = {s["name"] for s in m2["speakers"]}
    assert "Julius" in names
    print(f"Rename: Speaker 1 → Julius ✓")

    # --- 5) Merge-Speakers ---
    src = speaker_id_by_label["Speaker 2"]
    tgt = first_speaker_id
    moved = store.merge_speakers(mid, source_id=src, target_id=tgt)
    assert moved == 1, f"expected 1 turn moved, got {moved}"
    m3 = store.get_meeting(mid)
    assert m3 is not None
    assert len(m3["speakers"]) == 1, "after merge: exactly 1 speaker"
    assert all(t["speaker_id"] == tgt for t in m3["turns"]), "all turns now target"
    print(f"Merge: Speaker 2 → Julius ({moved} turn reassigned, 1 speaker remains)")

    # --- 6) list_meetings ---
    listing = store.list_meetings()
    assert len(listing) == 1
    assert listing[0]["id"] == mid
    print(f"List: 1 meeting visible")

    # --- 7) delete_meeting ---
    gone = store.delete_meeting(mid)
    assert gone
    assert store.get_meeting(mid) is None
    assert store.list_meetings() == []
    print(f"Delete: meeting removed, cascade OK")

    store.close()
    print("\nAll integration checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
