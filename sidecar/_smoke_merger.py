"""Smoke-Test für merger.merge.

Konstruiert synthetische Wort- und Segment-Streams, ruft den Merger,
prüft die Erwartungen. Keine externen Deps.

Run: python -m sidecar._smoke_merger
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sidecar.merger import merge  # noqa: E402


def _make_words(spec: list[tuple[int, int, str]]) -> list[dict]:
    return [{"t0_ms": t0, "t1_ms": t1, "text": txt} for (t0, t1, txt) in spec]


def _make_segs(spec: list[tuple[int, int, str]]) -> list[dict]:
    return [{"start_ms": s, "end_ms": e, "speaker": spk} for (s, e, spk) in spec]


def case_simple_two_speakers() -> None:
    """A-B-A wechsel: klare Segment-Grenzen, keine Überlappung."""
    words = _make_words(
        [
            (0, 500, "Hallo"),
            (500, 1000, "zusammen"),
            (1000, 1500, "heute"),
            (3000, 3500, "Danke"),
            (3500, 4000, "Max"),
            (6000, 6500, "Die"),
            (6500, 7000, "Statik"),
            (7000, 7500, "passt"),
        ]
    )
    segs = _make_segs(
        [
            (0, 2000, "SPEAKER_00"),   # Alice sagt "Hallo zusammen heute"
            (2500, 4500, "SPEAKER_01"), # Bob: "Danke Max"
            (5500, 8000, "SPEAKER_00"), # Alice: "Die Statik passt"
        ]
    )
    turns, speakers = merge(words, segs)
    assert len(turns) == 3, f"expected 3 turns, got {len(turns)}"
    assert turns[0].speaker_label == "Speaker 1"
    assert turns[1].speaker_label == "Speaker 2"
    assert turns[2].speaker_label == "Speaker 1"
    assert turns[0].text_raw == "Hallo zusammen heute"
    assert turns[1].text_raw == "Danke Max"
    assert turns[2].text_raw == "Die Statik passt"
    assert not any(t.overlap_flag for t in turns)
    assert len(speakers) == 2
    # Alice hat mehr Wörter und Zeit
    assert speakers[0].label == "Speaker 1"
    assert speakers[0].word_count == 6
    assert speakers[1].word_count == 2
    # Farben stabil aus Palette
    assert speakers[0].color.startswith("#")
    assert speakers[0].share_pct > speakers[1].share_pct
    print(f"  OK — {len(turns)} turns, {len(speakers)} speakers, "
          f"share {speakers[0].share_pct}/{speakers[1].share_pct}")


def case_tiny_segment_ignored() -> None:
    """Micro-Segment unter 300ms soll ignoriert werden."""
    words = _make_words(
        [
            (0, 500, "Ich"),
            (500, 1000, "sage"),
            (1000, 1500, "etwas"),
        ]
    )
    segs = _make_segs(
        [
            (0, 2000, "SPEAKER_00"),
            (800, 950, "SPEAKER_01"),  # 150ms — wird verworfen
        ]
    )
    turns, speakers = merge(words, segs)
    assert len(turns) == 1, f"expected 1 turn (micro ignored), got {len(turns)}"
    assert turns[0].speaker_label == "Speaker 1"
    assert len(speakers) == 1
    print(f"  OK — micro-segment correctly dropped")


def case_overlap_flag() -> None:
    """Zwei Sprecher überlappen stark auf demselben Wort — overlap_flag True."""
    words = _make_words([(0, 1000, "Wir"), (1000, 2000, "müssen")])
    # Beide sprechen zur selben Zeit, überlappen sich.
    segs = _make_segs(
        [
            (0, 2000, "SPEAKER_00"),
            (400, 1800, "SPEAKER_01"),  # fast gleich viel Overlap
        ]
    )
    turns, _ = merge(words, segs)
    assert any(t.overlap_flag for t in turns), "expected overlap_flag=True"
    print(f"  OK — overlap flagged on {sum(1 for t in turns if t.overlap_flag)} turn(s)")


def case_gap_creates_new_turn() -> None:
    """Langer Gap vom selben Sprecher → neuer Turn."""
    words = _make_words(
        [
            (0, 500, "Hallo"),
            (500, 1000, "alle"),
            (5000, 5500, "Nochmal"),  # 4s Gap > turn_gap_ms 1200
            (5500, 6000, "ich"),
        ]
    )
    segs = _make_segs([(0, 10000, "SPEAKER_00")])
    turns, _ = merge(words, segs)
    assert len(turns) == 2, f"expected split into 2 turns, got {len(turns)}"
    assert turns[0].text_raw == "Hallo alle"
    assert turns[1].text_raw == "Nochmal ich"
    print(f"  OK — gap correctly split turn")


def case_words_without_segments() -> None:
    """Diarization fällt aus — fallback auf Single-Speaker."""
    words = _make_words([(0, 500, "Test"), (500, 1000, "ohne"), (1000, 1500, "Segmente")])
    turns, speakers = merge(words, [])
    assert len(turns) == 1
    assert turns[0].speaker_label == "Speaker 1"
    assert len(speakers) == 1
    assert speakers[0].share_pct == 100.0
    print(f"  OK — fallback single-speaker")


def case_faster_whisper_input_shape() -> None:
    """Native faster-whisper shape: start/end in seconds, word key."""
    words = [
        {"start": 0.0, "end": 0.5, "word": "Hallo"},
        {"start": 0.5, "end": 1.0, "word": "Welt"},
    ]
    segs = [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
    ]
    turns, speakers = merge(words, segs)
    assert len(turns) == 1
    assert turns[0].text_raw == "Hallo Welt"
    assert turns[0].start_ms == 0
    assert turns[0].end_ms == 1000
    print(f"  OK — native faster-whisper input accepted")


def main() -> int:
    cases = [
        ("Simple two speakers", case_simple_two_speakers),
        ("Tiny segment ignored", case_tiny_segment_ignored),
        ("Overlap flag", case_overlap_flag),
        ("Gap → new turn", case_gap_creates_new_turn),
        ("Words without segments", case_words_without_segments),
        ("faster-whisper native shape", case_faster_whisper_input_shape),
    ]
    for name, fn in cases:
        print(f"=== {name} ===")
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL: {e}")
            return 1
        except Exception as e:
            print(f"  EXCEPTION: {type(e).__name__}: {e}")
            return 1
    print("\nAll cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
