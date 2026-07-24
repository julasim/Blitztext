"""Messaufbau: Normalisierung, WER, Referenz-Parser.

Diese Zahlen entscheiden später über ein Torch-Upgrade — also werden sie
gegen von Hand gerechnete Beispiele geprüft, nicht gegen sich selbst.
"""

from __future__ import annotations

from benchmark.metrics import compare_speakers, normalize_de, wer, words
from benchmark.reference import parse_reference, reference_path_for


# --- Normalisierung ---------------------------------------------------------


def test_normalisierung_vereinheitlicht_schreibweise():
    assert normalize_de("Der Fluchtweg, bitte!") == "der fluchtweg bitte"


def test_bindestrich_zaehlt_nicht_als_unterschied():
    """`OIB-Richtlinie` und `OIB Richtlinie` sind dieselbe Aussage."""
    assert normalize_de("OIB-Richtlinie") == normalize_de("OIB Richtlinie")


def test_umlaute_bleiben_erhalten():
    assert normalize_de("Grundstücksfläche") == "grundstücksfläche"


def test_zahlen_werden_nicht_normalisiert():
    """Bewusst: bei Normnummern und Kosten ist 12 vs. zwölf ein echter Fehler."""
    assert normalize_de("12") != normalize_de("zwölf")


def test_mehrfache_leerzeichen_und_zeilen():
    assert normalize_de("a   b\n\nc") == "a b c"


def test_leerer_text():
    assert normalize_de("") == ""
    assert words("") == []


# --- WER --------------------------------------------------------------------


def test_identischer_text_hat_wer_null():
    r = wer("der fluchtweg führt über den hof", "der fluchtweg führt über den hof")
    assert r.wer == 0.0
    assert (r.substitutions, r.deletions, r.insertions) == (0, 0, 0)


def test_ersetzung():
    r = wer("der fluchtweg führt über den hof", "der fluchtweg führt über den saal")
    assert r.substitutions == 1
    assert r.wer == 1 / 6


def test_loeschung():
    r = wer("a b c d", "a b d")
    assert r.deletions == 1
    assert r.wer == 1 / 4


def test_einfuegung():
    """Whisper halluziniert gern in Stille — Einfügungen müssen sichtbar sein."""
    r = wer("a b c", "a b c untertitel im auftrag des zdf")
    assert r.insertions == 5
    assert r.deletions == 0
    assert r.wer == 5 / 3


def test_gross_klein_und_satzzeichen_zaehlen_nicht():
    r = wer("Der Fluchtweg.", "der fluchtweg")
    assert r.wer == 0.0


def test_ohne_normalisierung_zaehlt_die_schreibweise():
    r = wer("Der Fluchtweg.", "der fluchtweg", normalize=False)
    assert r.wer > 0.0


def test_leere_referenz():
    assert wer("", "").wer == 0.0
    assert wer("", "etwas").wer == 1.0


def test_komplett_daneben():
    r = wer("a b c", "x y z")
    assert r.wer == 1.0
    assert r.substitutions == 3


# --- Sprecher ---------------------------------------------------------------


def test_sprecheranzahl_stimmt():
    r = compare_speakers(["Julius", "Max"], 2)
    assert r.difference == 0
    assert r.reference_count == 2


def test_zu_viele_sprecher_erkannt():
    """Der häufigste Diarization-Fehler: aus zwei Personen werden fünf."""
    r = compare_speakers(["Julius", "Max"], 5)
    assert r.difference == 3


def test_doppelte_namen_zaehlen_einmal():
    r = compare_speakers(["Julius", "Julius", "Max"], 2)
    assert r.reference_count == 2


# --- Referenz-Parser --------------------------------------------------------

EXPORT = """# Bauberatung Projekt Luisa

- **Datum:** 2026-07-24T09:00:00Z
- **Dauer:** 00:12:30
- **Sprecher:** 2

## Sprecher

- **Julius** — 60% (120 Wörter)
- **Max** — 40% (80 Wörter)

## Transkript

**[00:00:00] Julius**

Guten Morgen. Wir beginnen mit dem Brandschutz.

**[00:01:05] Max** ⚠︎ überlappende Rede

Der Fluchtweg soll über den Osthof geführt werden.
"""


def test_parser_liest_turns():
    ref = parse_reference(EXPORT)

    assert len(ref.turns) == 2
    assert ref.turns[0].speaker == "Julius"
    assert ref.turns[0].start_ms == 0
    assert ref.turns[0].text == "Guten Morgen. Wir beginnen mit dem Brandschutz."
    assert ref.turns[1].start_ms == 65_000
    assert ref.turns[1].overlap is True


def test_parser_ignoriert_den_kopfbereich():
    """Die Sprecherliste oben darf nicht im gesprochenen Text landen."""
    ref = parse_reference(EXPORT)

    assert "120 Wörter" not in ref.text
    assert "Bauberatung" not in ref.text


def test_parser_liefert_sprecher_in_reihenfolge():
    assert parse_reference(EXPORT).speakers == ["Julius", "Max"]


def test_parser_verbindet_mehrzeilige_absaetze():
    md = (
        "## Transkript\n\n**[00:00:00] A**\n\n"
        "Erste Zeile\nzweite Zeile\n\ndritter Absatz\n"
    )
    ref = parse_reference(md)

    assert ref.turns[0].text == "Erste Zeile zweite Zeile dritter Absatz"


def test_parser_ohne_kopfbereich():
    """Beim Korrigieren fliegt der Kopf gern raus — das muss reichen."""
    md = "## Transkript\n\n**[00:00:03] Julius**\n\nNur der Text.\n"
    ref = parse_reference(md)

    assert ref.turns[0].text == "Nur der Text."
    assert ref.turns[0].start_ms == 3000


def test_parser_toleriert_entfernten_overlap_marker():
    md = "## Transkript\n\n**[00:00:00] A**\n\nText.\n"
    assert parse_reference(md).turns[0].overlap is False


def test_parser_leeres_dokument():
    ref = parse_reference("")
    assert ref.turns == []
    assert ref.text == ""


def test_referenzpfad_neben_der_audiodatei():
    p = reference_path_for("C:/x/besprechung.mp3")
    assert p.name == "besprechung.reference.md"


# --- Diarization-Ausgabe (versionsfest) --------------------------------------


class _Turn:
    def __init__(self, start: float, end: float):
        self.start, self.end = start, end


def test_extract_segments_3x_itertracks():
    """pyannote 3.x: Annotation mit itertracks → 3-Tupel."""
    from sidecar.diarization import _extract_segments

    class FakeAnnotation:
        def itertracks(self, yield_label: bool = False):
            yield _Turn(0.0, 2.0), "A", "SPEAKER_00"
            yield _Turn(2.5, 4.0), "B", "SPEAKER_01"

    segs = _extract_segments(FakeAnnotation())

    assert segs == [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
        {"start": 2.5, "end": 4.0, "speaker": "SPEAKER_01"},
    ]


def test_extract_segments_4x_wrapper_mit_annotation():
    """pyannote 4.x: Wrapper-Objekt, dessen speaker_diarization eine
    Annotation ist — auspacken, dann itertracks."""
    from sidecar.diarization import _extract_segments

    class FakeAnnotation:
        def itertracks(self, yield_label: bool = False):
            yield _Turn(1.0, 3.0), "A", "SPEAKER_00"

    class FakeOutput:
        speaker_diarization = FakeAnnotation()

    segs = _extract_segments(FakeOutput())

    assert segs == [{"start": 1.0, "end": 3.0, "speaker": "SPEAKER_00"}]


def test_extract_segments_4x_direkt_iterierbar():
    """Die README-Form: direkt iterierbar mit 2-Tupeln."""
    from sidecar.diarization import _extract_segments

    class FakeOutput:
        speaker_diarization = [
            (_Turn(0.0, 1.5), "SPEAKER_00"),
            (_Turn(2.0, 3.0), "SPEAKER_01"),
        ]

    segs = _extract_segments(FakeOutput())

    assert [s["speaker"] for s in segs] == ["SPEAKER_00", "SPEAKER_01"]
    assert segs[0]["end"] == 1.5


# --- Modell-Cache-Umleitung -------------------------------------------------


def test_models_dir_override_hat_vorrang(tmp_path, monkeypatch):
    """BLITZTEXT_MODELS_DIR muss das APPDATA-Derivat schlagen — sonst lädt
    jeder isolierte Testlauf die Whisper-Gewichte (~3 GB) neu herunter."""
    from core.transcription import Transcriber

    override = tmp_path / "geteilter-cache"
    monkeypatch.setenv("APPDATA", str(tmp_path / "wegwerf"))
    monkeypatch.setenv("BLITZTEXT_MODELS_DIR", str(override))

    t = Transcriber(model_size="tiny")

    assert t._models_dir == str(override)
    assert override.is_dir(), "Verzeichnis muss angelegt werden"


def test_ohne_override_gilt_appdata(tmp_path, monkeypatch):
    from core.transcription import Transcriber

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("BLITZTEXT_MODELS_DIR", raising=False)

    t = Transcriber(model_size="tiny")

    assert t._models_dir == str(tmp_path / "Blitztext" / "models")


def test_explizites_models_dir_schlaegt_alles(tmp_path, monkeypatch):
    from core.transcription import Transcriber

    monkeypatch.setenv("BLITZTEXT_MODELS_DIR", str(tmp_path / "env"))
    explicit = tmp_path / "explizit"

    t = Transcriber(model_size="tiny", models_dir=str(explicit))

    assert t._models_dir == str(explicit)
