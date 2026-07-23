"""Pfad-Auflösung für den Stapel-Import.

Reines Dateisystem, keine Modelle — deshalb im Standardlauf.
"""

from __future__ import annotations

from pathlib import Path

from sidecar.audio_io import AUDIO_EXTENSIONS, expand_paths, is_supported


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_erkennt_gaengige_formate():
    assert is_supported("a.mp3")
    assert is_supported("A.MP3"), "Groß-/Kleinschreibung darf keine Rolle spielen"
    assert is_supported("b.wav")
    assert not is_supported("notiz.txt")
    assert not is_supported("ohne_endung")


def test_mp3_ist_dabei():
    assert ".mp3" in AUDIO_EXTENSIONS


def test_ordner_wird_rekursiv_und_sortiert_aufgeloest(tmp_path):
    _touch(tmp_path / "b.mp3")
    _touch(tmp_path / "a.mp3")
    _touch(tmp_path / "unterordner" / "c.wav")
    _touch(tmp_path / "notizen.txt")

    files, skipped = expand_paths([str(tmp_path)])

    namen = [f.name for f in files]
    assert namen == ["a.mp3", "b.mp3", "c.wav"], "alphabetisch, Unterordner inklusive"
    assert skipped == [], "die .txt im Ordner ist kein Grund für eine Meldung"


def test_einzelne_dateien_bleiben_in_angegebener_reihenfolge(tmp_path):
    zweite = _touch(tmp_path / "z.mp3")
    erste = _touch(tmp_path / "a.mp3")

    files, _ = expand_paths([str(zweite), str(erste)])

    assert [f.name for f in files] == ["z.mp3", "a.mp3"]


def test_nicht_unterstuetztes_format_wird_mit_grund_gemeldet(tmp_path):
    doc = _touch(tmp_path / "protokoll.docx")

    files, skipped = expand_paths([str(doc)])

    assert files == []
    assert len(skipped) == 1
    assert skipped[0]["path"] == str(doc)
    assert ".docx" in skipped[0]["reason"]


def test_fehlender_pfad_wird_gemeldet(tmp_path):
    files, skipped = expand_paths([str(tmp_path / "weg.mp3")])

    assert files == []
    assert skipped[0]["reason"] == "nicht gefunden"


def test_duplikate_werden_nur_einmal_eingereiht(tmp_path):
    f = _touch(tmp_path / "a.mp3")

    files, skipped = expand_paths([str(f), str(f), str(tmp_path)])

    assert len(files) == 1, "dieselbe Datei darf nicht dreimal transkribiert werden"
    assert all(s["reason"] == "doppelt" for s in skipped)


def test_leerer_ordner_meldet_sich(tmp_path):
    leer = tmp_path / "leer"
    leer.mkdir()

    files, skipped = expand_paths([str(leer)])

    assert files == []
    assert "keine Audiodateien" in skipped[0]["reason"]


def test_mischung_aus_datei_und_ordner(tmp_path):
    einzeln = _touch(tmp_path / "einzeln.mp3")
    ordner = tmp_path / "stapel"
    _touch(ordner / "1.mp3")
    _touch(ordner / "2.mp3")

    files, _ = expand_paths([str(einzeln), str(ordner)])

    assert [f.name for f in files] == ["einzeln.mp3", "1.mp3", "2.mp3"]
