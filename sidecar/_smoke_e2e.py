"""End-to-End-Smoke ohne pyannote/whisper.

Flow:
  1. Meeting anlegen + Turns via Merger erzeugen
  2. cleanup.run über alle Turns
  3. export.markdown (raw + cleaned)
  4. Inhalt prüfen

Lebendiger Test gegen die echten RPC-Methoden (inkl. Ollama).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="blitztext-e2e-")
    os.environ["APPDATA"] = tmp
    print(f"APPDATA isoliert: {tmp}\n")

    from sidecar import meeting_store as store
    from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict
    import sidecar.methods as m  # noqa: F401 — registers @method handlers
    from sidecar.rpc import call_method

    # --- Meeting anlegen ---
    words = [
        {"t0_ms": 0, "t1_ms": 600, "text": "Also"},
        {"t0_ms": 600, "t1_ms": 1100, "text": "ähm"},
        {"t0_ms": 1100, "t1_ms": 1600, "text": "ich"},
        {"t0_ms": 1600, "t1_ms": 2100, "text": "ich"},
        {"t0_ms": 2100, "t1_ms": 2700, "text": "dachte"},
        {"t0_ms": 2700, "t1_ms": 3200, "text": "wir"},
        {"t0_ms": 3200, "t1_ms": 3800, "text": "machen"},
        {"t0_ms": 3800, "t1_ms": 4300, "text": "die"},
        {"t0_ms": 4300, "t1_ms": 4900, "text": "Baueingabe"},
        {"t0_ms": 4900, "t1_ms": 5500, "text": "im"},
        {"t0_ms": 5500, "t1_ms": 6100, "text": "Mai"},
        # speaker wechselt
        {"t0_ms": 7000, "t1_ms": 7500, "text": "Das"},
        {"t0_ms": 7500, "t1_ms": 8000, "text": "passt"},
    ]
    segs = [
        {"start_ms": 0, "end_ms": 6500, "speaker": "SPEAKER_00"},
        {"start_ms": 6800, "end_ms": 8200, "speaker": "SPEAKER_01"},
    ]

    turns, speakers = merge(words, segs)
    print(f"Merger: {len(turns)} turns, {len(speakers)} speakers")

    mid = store.create_meeting(
        title="Jour fixe — Projekt Sophia",
        duration_ms=8200,
        language="de",
        whisper_model="large-v3-turbo",
        diar_model="pyannote/speaker-diarization-3.1",
        status="ready",
    )

    store.upsert_speakers(mid, [speaker_to_store_dict(s) for s in speakers])
    persisted = store.get_meeting(mid)
    assert persisted is not None
    label_to_id = {s["label"]: s["id"] for s in persisted["speakers"]}
    store.upsert_turns(mid, [turn_to_store_dict(t, label_to_id) for t in turns])

    # --- Sprecher umbenennen, damit Export menschlich aussieht ---
    call_method("speaker.rename", {
        "meeting_id": mid,
        "speaker_id": label_to_id["Speaker 1"],
        "name": "Julius",
    })
    call_method("speaker.rename", {
        "meeting_id": mid,
        "speaker_id": label_to_id["Speaker 2"],
        "name": "Max",
    })
    print("Renamed: Speaker 1 → Julius, Speaker 2 → Max")

    # --- Cleanup durch Ollama jagen ---
    print("\nRunning cleanup.run... (~10-30s, Ollama-call pro Turn)")
    result = call_method("cleanup.run", {"meeting_id": mid})
    print(f"  {result}")
    assert result["processed"] >= 1

    cleaned = store.get_meeting(mid)
    assert cleaned is not None
    for t in cleaned["turns"]:
        print(f"  RAW:     {t['text_raw']}")
        print(f"  CLEAN:   {t['text_clean']}")
        print()

    # --- Export: raw ---
    raw_path = Path(tmp) / "export_raw.md"
    r1 = call_method(
        "export.markdown",
        {"meeting_id": mid, "path": str(raw_path), "use_cleanup": False},
    )
    print(f"Raw export: {r1}")
    content_raw = raw_path.read_text(encoding="utf-8")
    assert "Jour fixe" in content_raw
    assert "Julius" in content_raw
    assert "Baueingabe" in content_raw
    assert "## Transkript" in content_raw

    # --- Export: cleaned ---
    clean_path = Path(tmp) / "export_clean.md"
    r2 = call_method(
        "export.markdown",
        {"meeting_id": mid, "path": str(clean_path), "use_cleanup": True},
    )
    print(f"Clean export: {r2}")
    content_clean = clean_path.read_text(encoding="utf-8")
    assert "Julius" in content_clean

    print("\n--- RAW MARKDOWN (first 400 chars) ---")
    print(content_raw[:400])
    print("\n--- CLEANED MARKDOWN (first 400 chars) ---")
    print(content_clean[:400])

    print("\nE2E passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
