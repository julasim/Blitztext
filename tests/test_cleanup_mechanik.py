"""Cleanup-Mechanik ohne LLM: Idempotenz je Stufe, Doppelstart, Fehlerpfad.

Warum getrennt von `test_cleanup.py`: dort läuft alles gegen ein echtes
Ollama und ist mit `--ollama` markiert — auf dieser Maschine also **nie**.
Damit war der zweitkomplexeste Codepfad des Produkts faktisch ungetestet,
und der Fehler, der die Idempotenz seit ihrer Einführung wirkungslos machte
(`text_clean_mode` fehlte in der SELECT-Liste), fiel niemandem auf.

Hier wird `cleanup_turn` eingesetzt statt ein Modell gefragt. Geprüft wird
die Ablauflogik — und die braucht kein LLM.
"""

from __future__ import annotations

import threading

import pytest

import sidecar.methods as methods
from sidecar.rpc import RpcError, call_method


@pytest.fixture
def cleanup_umgebung(store, monkeypatch):
    """Ollama vortäuschen, LLM einsetzen, Events einsammeln."""
    monkeypatch.setattr(methods, "_ollama_available", lambda: True)

    aufrufe: list[str] = []

    def _fake_cleanup(text, prev_text=None, next_text=None, model=None, mode="faithful"):
        aufrufe.append(text)
        return f"[{mode}] {text}"

    monkeypatch.setattr(methods, "cleanup_turn", _fake_cleanup)

    ereignisse: list[tuple[str, dict]] = []
    fertig = threading.Event()

    def _sammle(name: str, payload: dict | None = None) -> None:
        ereignisse.append((name, payload or {}))
        if name == "cleanup.done" or (name == "cleanup.error" and (payload or {}).get("fatal")):
            fertig.set()

    monkeypatch.setattr(methods, "emit_event", _sammle)
    return aufrufe, ereignisse, fertig


def _warte(fertig: threading.Event, sekunden: float = 10.0) -> bool:
    return fertig.wait(timeout=sekunden)


def test_zweiter_lauf_derselben_stufe_ueberspringt_alles(
    store, sample_meeting, cleanup_umgebung
):
    """Der Fehler, der die Idempotenz wirkungslos machte.

    `get_meeting` lieferte `text_clean_mode` nicht mit, die Skip-Bedingung in
    `cleanup.run` prüfte aber genau darauf. Jeder weitere Lauf schickte damit
    **alle** Absätze erneut durchs LLM und überschrieb bereits geprüfte
    Fassungen.
    """
    aufrufe, _ereignisse, fertig = cleanup_umgebung

    call_method("cleanup.run", {"meeting_id": sample_meeting})
    assert _warte(fertig)
    erste_runde = len(aufrufe)
    assert erste_runde > 0

    # Zweiter Lauf, gleiche Stufe: nichts darf erneut durchs LLM.
    fertig.clear()
    aufrufe.clear()
    call_method("cleanup.run", {"meeting_id": sample_meeting})
    assert _warte(fertig)

    assert aufrufe == [], "in derselben Stufe darf nichts neu gerechnet werden"


def test_stufenwechsel_rechnet_neu(store, sample_meeting, cleanup_umgebung):
    """Ein Wechsel faithful → readable muss die Absätze neu bereinigen —
    sonst bliebe der Umschalter in der Oberfläche wirkungslos."""
    aufrufe, _ereignisse, fertig = cleanup_umgebung

    call_method("cleanup.run", {"meeting_id": sample_meeting, "mode": "faithful"})
    assert _warte(fertig)
    erste_runde = len(aufrufe)

    fertig.clear()
    aufrufe.clear()
    call_method("cleanup.run", {"meeting_id": sample_meeting, "mode": "readable"})
    assert _warte(fertig)

    assert len(aufrufe) == erste_runde, "andere Stufe ⇒ alles neu"
    turns = store.get_meeting(sample_meeting)["turns"]
    assert all(t["text_clean_mode"] == "readable" for t in turns)
    assert all(t["text_clean"].startswith("[readable]") for t in turns)


def test_zweiter_lauf_waehrend_der_erste_laeuft_wird_abgewiesen(
    store, sample_meeting, monkeypatch, cleanup_umgebung
):
    """Zwei Worker auf denselben Absätzen würden sich überschreiben."""
    _aufrufe, _ereignisse, fertig = cleanup_umgebung
    blockiere = threading.Event()

    def _langsam(text, prev_text=None, next_text=None, model=None, mode="faithful"):
        blockiere.wait(timeout=5)
        return text

    monkeypatch.setattr(methods, "cleanup_turn", _langsam)

    call_method("cleanup.run", {"meeting_id": sample_meeting})
    try:
        with pytest.raises(RpcError, match="bereits ein Cleanup"):
            call_method("cleanup.run", {"meeting_id": sample_meeting})
    finally:
        blockiere.set()
        _warte(fertig)


def test_nach_dem_lauf_ist_wieder_ein_start_moeglich(
    store, sample_meeting, cleanup_umgebung
):
    """Die Sperre muss auch nach einem Fehler fallen — sonst wäre das
    Meeting dauerhaft blockiert."""
    _aufrufe, _ereignisse, fertig = cleanup_umgebung

    call_method("cleanup.run", {"meeting_id": sample_meeting})
    assert _warte(fertig)

    fertig.clear()
    res = call_method("cleanup.run", {"meeting_id": sample_meeting})
    assert res["ok"] is True
    assert _warte(fertig)


def test_ein_misslungener_absatz_stoppt_den_lauf_nicht(
    store, sample_meeting, monkeypatch, cleanup_umgebung
):
    """`cleanup.error` kommt pro Absatz und ist **nicht** fatal; der Worker
    macht weiter und schickt am Ende trotzdem ein `cleanup.done`."""
    _aufrufe, ereignisse, fertig = cleanup_umgebung
    zaehler = {"n": 0}

    def _erster_faellt_aus(text, prev_text=None, next_text=None, model=None, mode="faithful"):
        zaehler["n"] += 1
        if zaehler["n"] == 1:
            raise RuntimeError("Modell antwortet nicht")
        return f"[{mode}] {text}"

    monkeypatch.setattr(methods, "cleanup_turn", _erster_faellt_aus)

    call_method("cleanup.run", {"meeting_id": sample_meeting})
    assert _warte(fertig), "trotz Fehler muss der Lauf zu Ende gehen"

    namen = [n for n, _ in ereignisse]
    fehler = [p for n, p in ereignisse if n == "cleanup.error"]
    assert "cleanup.done" in namen
    assert fehler and fehler[0]["fatal"] is False
    assert zaehler["n"] > 1, "nach dem Fehler muss weitergearbeitet werden"


def test_ohne_ollama_gibt_es_einen_klaren_fehler(store, sample_meeting, monkeypatch):
    """Statt alle Absätze einzeln auflaufen zu lassen."""
    monkeypatch.setattr(methods, "_ollama_available", lambda: False)

    with pytest.raises(RpcError, match="Ollama ist nicht erreichbar"):
        call_method("cleanup.run", {"meeting_id": sample_meeting})
