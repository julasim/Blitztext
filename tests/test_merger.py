"""Merger: Wort-Zeitstempel + Sprecher-Segmente → Turns.

Die anspruchsvollste Logik im Projekt und die einzige, die ohne Modelle
vollständig prüfbar ist — synthetische Streams rein, Turns raus.

Portiert aus sidecar/_smoke_merger.py.
"""

from __future__ import annotations

from sidecar.merger import merge, normalize_word_spacing


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


# --- Textnormalisierung -----------------------------------------------------


def test_bindestrich_wird_zusammengezogen():
    """Whisper gibt Wörter einzeln aus; beim Zusammenfügen entsteht
    „Karl -Heinz". Im echten Transkript der PPSV-Besprechung gesehen."""
    assert normalize_word_spacing("Servus Karl -Heinz") == "Servus Karl-Heinz"
    assert normalize_word_spacing("Karl- Heinz") == "Karl-Heinz"


def test_gedankenstrich_bleibt_stehen():
    """Beidseitige Leerzeichen = Gedankenstrich, kein Bindestrich. Das
    Kriterium trägt, weil Whisper den Bindestrich am Wort belässt
    („-Heinz") und einen Gedankenstrich als eigenes Token ausgibt."""
    assert normalize_word_spacing("Ja - also gut") == "Ja - also gut"


def test_leerzeichen_vor_satzzeichen_verschwindet():
    assert normalize_word_spacing("Wort , nächstes") == "Wort, nächstes"
    assert normalize_word_spacing("Ende ?") == "Ende?"


def test_mehrfache_leerzeichen():
    assert normalize_word_spacing("a    b") == "a b"


def test_normalisierung_laesst_wort_zeitstempel_unberuehrt():
    """Kritisch: aus `words` entstehen später Untertitel. Wenn der Fließtext
    normalisiert wird, die Wortliste aber nicht, dürfen sie nicht
    auseinanderlaufen — die Wortliste ist die Wahrheit."""
    words = _words([(0, 500, "Karl"), (500, 1000, "-Heinz")])
    segs = _segs([(0, 1500, "SPEAKER_00")])

    turns, _ = merge(words, segs)

    assert turns[0].text_raw == "Karl-Heinz"
    assert [w["w"] for w in turns[0].words] == ["Karl", "-Heinz"]


# --- Satzgrenzen ------------------------------------------------------------


def test_pause_mitten_im_satz_zerschneidet_nicht():
    """1,4 s Pause ohne Satzzeichen davor: der Sprecher holt Luft, der Satz
    läuft weiter. Vorher entstand hier ein Absatzumbruch."""
    words = _words(
        [
            (0, 500, "Der"),
            (500, 1000, "Fluchtweg"),
            (2400, 2900, "führt"),  # 1,4 s Pause, kein Satzzeichen
            (2900, 3400, "hinaus."),
        ]
    )
    segs = _segs([(0, 4000, "SPEAKER_00")])

    turns, _ = merge(words, segs)

    assert len(turns) == 1
    assert turns[0].text_raw == "Der Fluchtweg führt hinaus."


def test_pause_nach_satzende_zerschneidet_weiterhin():
    """Punkt davor: der Satz ist fertig, ein neuer Absatz ist richtig."""
    words = _words(
        [
            (0, 500, "Erster"),
            (500, 1000, "Satz."),
            (2400, 2900, "Zweiter"),  # dieselbe Pause, aber Satz war zu
            (2900, 3400, "Satz."),
        ]
    )
    segs = _segs([(0, 4000, "SPEAKER_00")])

    turns, _ = merge(words, segs)

    assert [t.text_raw for t in turns] == ["Erster Satz.", "Zweiter Satz."]


def test_sehr_lange_pause_zerschneidet_auch_ohne_satzzeichen():
    """Die Kulanz hat eine Grenze — sonst wächst ein Turn ins Unendliche,
    nur weil jemand den Satz nie beendet hat."""
    words = _words(
        [
            (0, 500, "Also"),
            (500, 1000, "wir"),
            (5000, 5500, "genau"),  # 4 s — jenseits von sentence_grace_ms
        ]
    )
    segs = _segs([(0, 6000, "SPEAKER_00")])

    turns, _ = merge(words, segs)

    assert len(turns) == 2


def test_satzgrenzen_regel_abschaltbar():
    words = _words([(0, 500, "Der"), (2400, 2900, "Fluchtweg")])
    segs = _segs([(0, 3000, "SPEAKER_00")])

    turns, _ = merge(words, segs, sentence_grace_ms=0)

    assert len(turns) == 2, "ohne Kulanz gilt wieder turn_gap_ms"


# --- Kurze Einwürfe ---------------------------------------------------------


def test_kurzer_einwurf_zerschneidet_den_hauptsprecher_nicht():
    """„mhm" mitten im Satz: der Einwurf bleibt als eigener Turn erhalten,
    aber der Hauptsprecher wird nicht in zwei Absätze zerhackt."""
    words = _words(
        [
            (0, 500, "Wir"),
            (500, 1000, "brauchen"),
            (1100, 1400, "Mhm"),  # 300 ms Einwurf
            (1500, 2000, "eine"),
            (2000, 2500, "Freigabe."),
        ]
    )
    segs = _segs(
        [
            (0, 1050, "SPEAKER_00"),
            (1100, 1450, "SPEAKER_01"),
            (1500, 2600, "SPEAKER_00"),
        ]
    )

    turns, _ = merge(words, segs)

    haupt = [t for t in turns if t.speaker_label == "Speaker 1"]
    assert len(haupt) == 1, "Hauptsprecher darf nicht zerschnitten werden"
    assert haupt[0].text_raw == "Wir brauchen eine Freigabe."
    assert any(t.text_raw == "Mhm" for t in turns), "Einwurf bleibt erhalten"


def test_turns_bleiben_zeitlich_sortiert():
    """Nach dem Verbinden über einen Einwurf hinweg muss die Reihenfolge
    stimmen — sonst steht der Einwurf im Protokoll an falscher Stelle."""
    words = _words(
        [(0, 500, "A1"), (600, 900, "B"), (1000, 1500, "A2")]
    )
    segs = _segs(
        [(0, 550, "SPEAKER_00"), (600, 950, "SPEAKER_01"), (1000, 1600, "SPEAKER_00")]
    )

    turns, _ = merge(words, segs)

    starts = [t.start_ms for t in turns]
    assert starts == sorted(starts)
    assert [t.idx for t in turns] == list(range(len(turns)))


def test_langer_fremdbeitrag_zerschneidet_weiterhin():
    """Kein Einwurf, sondern ein echter Redebeitrag — hier ist der Schnitt
    richtig."""
    words = _words(
        [
            (0, 500, "Wir"),
            (1000, 3000, "Das"),
            (3000, 4000, "sehe"),
            (4000, 5000, "ich"),
            (5500, 6000, "auch"),
        ]
    )
    segs = _segs(
        [(0, 600, "SPEAKER_00"), (1000, 5100, "SPEAKER_01"), (5500, 6100, "SPEAKER_00")]
    )

    turns, _ = merge(words, segs)

    assert len([t for t in turns if t.speaker_label == "Speaker 1"]) == 2


def test_einwurf_bruecke_abschaltbar():
    words = _words([(0, 500, "A1"), (600, 900, "B"), (1000, 1500, "A2")])
    segs = _segs(
        [(0, 550, "SPEAKER_00"), (600, 950, "SPEAKER_01"), (1000, 1600, "SPEAKER_00")]
    )

    turns, _ = merge(words, segs, bridge_interjection_ms=0)

    assert len(turns) == 3, "ohne Brücke drei getrennte Turns"
