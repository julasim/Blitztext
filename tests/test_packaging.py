"""Bündelung: was in `build-sidecar.spec` ausgeschlossen wird, darf zur
Laufzeit nicht gebraucht werden.

Warum es diese Datei gibt
-------------------------
Die 0.2.0 ist mit einer kaputten Sprechertrennung ausgeliefert worden.
`pandas` stand in der `excludes`-Liste, mit der Begründung „wir nutzen es
nicht; pyannote zieht es aber mit". Das stimmte nicht: `pyannote.database.util`
importiert pandas auf **Modulebene**, und diese Datei liegt in der Importkette
von `pyannote.audio`. Im gepackten Sidecar ließ sich pyannote deshalb nicht
laden — jedes Transkript hatte genau einen Sprecher, und im Log stand eine
Meldung, die eine ganz andere Ursache behauptete.

Auffallen konnte das nur auf der Zielmaschine: in der Entwicklungs-venv ist
pandas installiert, der Dev-Modus lief also einwandfrei.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

SPEC = Path(__file__).resolve().parent.parent / "build-sidecar.spec"


def _excludes_aus_spec() -> list[str]:
    """Die `excludes`-Liste aus der Spec lesen, ohne sie auszuführen."""
    quelltext = SPEC.read_text(encoding="utf-8")
    # Die Spec ist kein importierbares Modul (PyInstaller-Globals fehlen),
    # deshalb über den Syntaxbaum statt über einen Import.
    baum = ast.parse(quelltext)
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        if not (isinstance(knoten.func, ast.Name) and knoten.func.id == "Analysis"):
            continue
        for kwarg in knoten.keywords:
            if kwarg.arg == "excludes" and isinstance(kwarg.value, ast.List):
                return [
                    e.value
                    for e in kwarg.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
    pytest.fail("excludes-Liste in build-sidecar.spec nicht gefunden")


def test_spec_hat_eine_excludes_liste():
    excludes = _excludes_aus_spec()

    assert excludes, "ohne excludes wäre das Paket unnötig groß"
    assert "tkinter" in excludes, "Grundbestand der Liste fehlt — falsch geparst?"


def test_pandas_ist_nicht_ausgeschlossen():
    """Der konkrete Fehler, der die 0.2.0 unbrauchbar gemacht hat.

    Eigener Test neben der allgemeinen Prüfung unten, weil dieser hier ohne
    Modelle und ohne `--slow` läuft — er greift also in jedem Standardlauf.
    """
    assert "pandas" not in _excludes_aus_spec(), (
        "pandas wird von pyannote.database.util auf Modulebene importiert. "
        "Steht es in excludes, lädt pyannote im gepackten Sidecar nicht und "
        "die Sprechertrennung fällt still aus."
    )


@pytest.mark.slow
def test_kein_ausgeschlossenes_modul_wird_zur_laufzeit_geladen():
    """Die allgemeine Fassung: importiert die schweren Laufzeit-Module und
    prüft, dass keins der ausgeschlossenen Pakete dabei mitkommt.

    Braucht torch und pyannote (~15 s), deshalb hinter `--slow`. Das ist die
    Prüfung, die den pandas-Fehler von sich aus gefunden hätte — ohne dass
    jemand hätte wissen müssen, dass ausgerechnet pandas das Problem ist.
    """
    import os

    os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

    excludes = set(_excludes_aus_spec())
    # Ein Eintrag mit Punkt schließt NUR dieses Untermodul aus: `PIL.ImageQt`
    # zu verbieten heißt nicht, dass PIL selbst fehlen darf. Beide Fälle
    # deshalb getrennt vergleichen.
    ganze_pakete = {e for e in excludes if "." not in e}
    untermodule = {e for e in excludes if "." in e}

    from pyannote.audio import Pipeline  # noqa: F401
    from faster_whisper.audio import decode_audio  # noqa: F401

    geladen = set(sys.modules)
    kollision = sorted(ganze_pakete & {n.split(".")[0] for n in geladen})
    kollision += sorted(untermodule & geladen)

    assert not kollision, (
        f"Diese Pakete stehen in excludes, werden aber zur Laufzeit geladen: "
        f"{kollision}. Im gepackten Sidecar fehlen sie dann — der Fehler "
        f"tritt erst auf der Zielmaschine auf."
    )


def test_spec_deckt_die_function_local_importe_ab():
    """Module, die nur innerhalb von Funktionen importiert werden, sieht
    PyInstallers Bytecode-Scan nicht — sie müssen in `hiddenimports` stehen.

    Geprüft werden die eigenen Pakete: jedes Modul unter `sidecar/` und
    `core/` muss dort auftauchen, weil der Sidecar-Start bewusst schlank ist
    und fast alles verzögert importiert.
    """
    quelltext = SPEC.read_text(encoding="utf-8")
    wurzel = SPEC.parent

    fehlend: list[str] = []
    for paket in ("sidecar", "core"):
        for datei in sorted((wurzel / paket).glob("*.py")):
            if datei.stem.startswith("_"):
                continue  # __init__/__main__ kommen über den Entry-Point
            name = f"{paket}.{datei.stem}"
            if not re.search(rf'"{re.escape(name)}"', quelltext):
                fehlend.append(name)

    assert not fehlend, (
        f"Diese Module fehlen in build-sidecar.spec (hiddenimports): {fehlend}"
    )
