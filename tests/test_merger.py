"""Merger: Wort-Zeitstempel + Sprecher-Segmente → Turns.

Die anspruchsvollste Logik im Projekt und die einzige, die ohne Modelle
vollständig prüfbar ist — synthetische Streams rein, Turns raus.

Portiert aus sidecar/_smoke_merger.py.
"""

from __future__ import annotations

from sidecar.merger import merge


def _words(spec: list[tuple[int, int, str]]) -> list[dict]:
    return [{"t0_ms": t0, "t1_ms": t1, "text": txt} for (t0, t1, txt) in spec]


def _segs(spec: list[tuple[int, int, str]]) -> list[dict]:
    return [{"start_ms": s, "end_ms": e, "speaker": spk} for (s, e, spk) in spec]


def test_zwei_sprecher_im_wechsel():
    """A-B-A: klare Segmentgrenzen, keine Überlappung."""
    words = _words(
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
    segs = _segs(
        [
            (0, 2000, "SPEAKER_00"),
            (2500, 4500, "SPEAKER_01"),
            (5500, 8000, "SPEAKER_00"),
        ]
    )

    turns, speakers = merge(words, segs)

    assert [t.speaker_label for t in turns] == ["Speaker 1", "Speaker 2", "Speaker 1"]
    assert [t.text_raw for t in turns] == [
        "Hallo zusammen heute",
        "Danke Max",
        "Die Statik passt",
    ]
    assert not any(t.overlap_flag for t in turns)

    assert len(speakers) == 2
    assert speakers[0].label == "Speaker 1"
    assert speakers[0].word_count == 6
    assert speakers[1].word_count == 2
    assert speakers[0].share_pct > speakers[1].share_pct
    assert speakers[0].color.startswith("#")


def test_mikro_segment_wird_verworfen():
    """Ein 150-ms-Einwurf erzeugt keinen eigenen Sprecher (Grenze: 300 ms)."""
    words = _words([(0, 500, "Ich"), (500, 1000, "sage"), (1000, 1500, "etwas")])
    segs = _segs([(0, 2000, "SPEAKER_00"), (800, 950, "SPEAKER_01")])

    turns, speakers = merge(words, segs)

    assert len(turns) == 1
    assert turns[0].speaker_label == "Speaker 1"
    assert len(speakers) == 1


def test_kreuzreden_wird_markiert():
    """Zwei Sprecher überlappen stark → overlap_flag."""
    words = _words([(0, 1000, "Wir"), (1000, 2000, "müssen")])
    segs = _segs([(0, 2000, "SPEAKER_00"), (400, 1800, "SPEAKER_01")])

    turns, _ = merge(words, segs)

    assert any(t.overlap_flag for t in turns)


def test_lange_pause_teilt_den_turn():
    """Derselbe Sprecher, 4 s Pause → zwei Turns (Grenze: 1200 ms)."""
    words = _words(
        [
            (0, 500, "Hallo"),
            (500, 1000, "alle"),
            (5000, 5500, "Nochmal"),
            (5500, 6000, "ich"),
        ]
    )
    segs = _segs([(0, 10000, "SPEAKER_00")])

    turns, _ = merge(words, segs)

    assert [t.text_raw for t in turns] == ["Hallo alle", "Nochmal ich"]


def test_ohne_segmente_ein_sprecher():
    """Diarization ausgefallen → nutzbares Transkript statt Abbruch.

    Das ist der Pfad, den `run_stages` nimmt, wenn pyannote nicht lädt.
    """
    words = _words([(0, 500, "Test"), (500, 1000, "ohne"), (1000, 1500, "Segmente")])

    turns, speakers = merge(words, [])

    assert len(turns) == 1
    assert turns[0].speaker_label == "Speaker 1"
    assert speakers[0].share_pct == 100.0


def test_akzeptiert_native_faster_whisper_form():
    """faster-whisper liefert Sekunden und `word`/`start`/`end` statt ms."""
    words = [
        {"start": 0.0, "end": 0.5, "word": "Hallo"},
        {"start": 0.5, "end": 1.0, "word": "Welt"},
    ]
    segs = [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"}]

    turns, _ = merge(words, segs)

    assert turns[0].text_raw == "Hallo Welt"
    assert turns[0].start_ms == 0
    assert turns[0].end_ms == 1000


def test_leerer_input():
    """Whisper hat nichts erkannt — darf nicht knallen."""
    turns, speakers = merge([], [])

    assert turns == []
    assert speakers == []
