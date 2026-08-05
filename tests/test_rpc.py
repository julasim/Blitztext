"""JSON-RPC-Transport: Dispatch, Fehlerform, Notifications.

Die Schicht, über die *jede* Anfrage aus der App läuft. Sie hat keine
Abhängigkeiten außer der Standardbibliothek — es gibt keinen Grund, sie
ungetestet zu lassen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from sidecar import rpc


def test_unbekannte_methode():
    resp = rpc._dispatch({"jsonrpc": "2.0", "id": 1, "method": "gibt.es.nicht"})

    assert resp is not None
    assert resp["error"]["code"] == rpc.METHOD_NOT_FOUND
    assert "id" in resp and resp["id"] == 1


def test_fehlende_methode_ist_ungueltige_anfrage():
    resp = rpc._dispatch({"jsonrpc": "2.0", "id": 1})

    assert resp is not None
    assert resp["error"]["code"] == rpc.INVALID_REQUEST


def test_falsche_parameter_werden_zu_invalid_params():
    resp = rpc._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"unbekannt": 1}}
    )

    assert resp is not None
    assert resp["error"]["code"] == rpc.INVALID_PARAMS


def test_typeerror_aus_der_methode_ist_kein_parameterfehler():
    """Ein `TypeError` **im** Methodenrumpf ist ein echter Fehler.

    Vorher lag ein `except TypeError` um den Aufruf herum: jeder TypeError aus
    dem Inneren wurde zu `INVALID_PARAMS` — mit der Meldung des inneren
    Fehlers, aber **ohne Traceback**. Man sah also „ungültige Parameter" und
    hatte keinen Hinweis, wo es wirklich knallte. Die Signatur wird jetzt
    vorab geprüft; alles danach fällt in den generischen Zweig.
    """

    @rpc.method("test.wirft_typeerror")
    def _wirft() -> dict:
        return {"summe": 1 + "zwei"}  # type: ignore[operator]

    try:
        resp = rpc._dispatch(
            {"jsonrpc": "2.0", "id": 7, "method": "test.wirft_typeerror"}
        )

        assert resp is not None
        assert resp["error"]["code"] == rpc.INTERNAL_ERROR, (
            "TypeError aus dem Rumpf darf nicht als Parameterfehler erscheinen"
        )
        spur = resp["error"]["data"]["traceback"]
        assert "TypeError" in spur
        assert "_wirft" in spur, "der Traceback muss bis in den Rumpf reichen"
    finally:
        rpc._methods.pop("test.wirft_typeerror", None)


def test_notification_bekommt_keine_antwort():
    """Ohne `id` ist es eine Notification — laut Spec kommt nichts zurück."""
    assert rpc._dispatch({"jsonrpc": "2.0", "method": "ping"}) is None


def test_ping_antwortet_mit_version():
    resp = rpc._dispatch({"jsonrpc": "2.0", "id": 7, "method": "ping"})

    assert resp is not None
    assert resp["id"] == 7
    assert resp["result"]["ok"] is True
    assert resp["result"]["version"] == rpc.__version__


def test_ausnahme_wird_zu_internal_error_mit_traceback():
    """Ein Fehler in einer Methode darf den Sidecar nie beenden — er muss
    als strukturierte Antwort zurückkommen."""

    @rpc.method("test.kracht")
    def _kracht():
        raise ValueError("absichtlich")

    try:
        resp = rpc._dispatch({"jsonrpc": "2.0", "id": 2, "method": "test.kracht"})

        assert resp is not None
        assert resp["error"]["code"] == rpc.INTERNAL_ERROR
        assert "absichtlich" in resp["error"]["message"]
        assert "traceback" in resp["error"]["data"]
    finally:
        rpc._methods.pop("test.kracht", None)


def test_rpc_error_behaelt_seinen_code():
    @rpc.method("test.nicht_gefunden")
    def _nf():
        raise rpc.RpcError(rpc.APP_NOT_FOUND, "weg")

    try:
        resp = rpc._dispatch({"jsonrpc": "2.0", "id": 3, "method": "test.nicht_gefunden"})

        assert resp is not None
        assert resp["error"]["code"] == rpc.APP_NOT_FOUND
        assert resp["error"]["message"] == "weg"
    finally:
        rpc._methods.pop("test.nicht_gefunden", None)


def test_doppelte_registrierung_faellt_beim_import_auf():
    with pytest.raises(RuntimeError):
        rpc.method("ping")(lambda: None)


def test_events_gehen_als_notification_ohne_id_raus(capsys):
    """Die Rust-Seite unterscheidet Antwort und Event allein an der `id`."""
    rpc.emit_event("meeting.progress", {"meeting_id": "abc", "pct": 0.5})

    line = capsys.readouterr().out.strip()
    msg = json.loads(line)

    assert "id" not in msg
    assert msg["method"] == "meeting.progress"
    assert msg["params"]["pct"] == 0.5


def test_events_schreiben_umlaute_unescaped(capsys):
    """ensure_ascii=False — sonst kommen \\u00fc-Sequenzen im UI an."""
    rpc.emit_event("meeting.error", {"message": "Datei konnte nicht geöffnet werden"})

    line = capsys.readouterr().out.strip()

    assert "geöffnet" in line
    assert json.loads(line)["params"]["message"].endswith("geöffnet werden")


def test_versionen_stimmen_ueberein():
    """Die Version steht an drei Stellen — sie müssen zusammenpassen.

    Die Statusleiste der App zeigt `rpc.__version__`. Das stand bis
    2026-08-05 auf `0.1.0-alpha`, während das Produkt als 0.2.0 gebaut und
    ausgeliefert wurde — und ausgerechnet die Abnahmeliste in BUILD.md
    verlangt einen Blick auf genau diese Anzeige.
    """
    wurzel = Path(__file__).resolve().parent.parent

    tauri = json.loads((wurzel / "app/src-tauri/tauri.conf.json").read_text("utf-8"))
    paket = json.loads((wurzel / "app/package.json").read_text("utf-8"))
    cargo = (wurzel / "app/src-tauri/Cargo.toml").read_text("utf-8")
    treffer = re.search(r'(?m)^version\s*=\s*"([^"]+)"', cargo)
    assert treffer, "Cargo.toml ohne version-Feld"

    versionen = {
        "tauri.conf.json": tauri["version"],
        "Cargo.toml": treffer.group(1),
        "package.json": paket["version"],
        "sidecar/rpc.py": rpc.__version__,
    }

    assert len(set(versionen.values())) == 1, f"Versionen driften: {versionen}"
