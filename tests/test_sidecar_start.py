"""Der Sidecar als Prozess: Start, stdio-Transport, RPC-Vertrag.

Die letzte große Deckungslücke. `test_rpc.py` prüft `_dispatch` als Funktion —
nie aber den Weg, den das ausgelieferte Produkt tatsächlich geht: Prozess
starten, ndjson über stdin/stdout, Antworten per `id` zuordnen. Auch
`recover_orphans()` läuft nur hier, weil nur `__main__` die Warteschlange
startet.

Zweiter Zweck: Feld-Drift zwischen Sidecar und Frontend fangen. TypeScript
prüft die *deklarierten* Typen; ob der Sidecar ein Feld wirklich liefert,
sagt kein `tsc`. Diese Runde hat drei Felder ergänzt und eines umbenannt.

`--slow`, weil der Start torch und pyannote lädt (~30 s).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

PROJEKT = Path(__file__).resolve().parent.parent


class SidecarProzess:
    """Startet `python -m sidecar` und spricht ndjson mit ihm."""

    def __init__(self, appdata: Path) -> None:
        umgebung = dict(os.environ)
        umgebung["APPDATA"] = str(appdata)
        umgebung["PYTHONIOENCODING"] = "utf-8"
        umgebung["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "sidecar"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(PROJEKT),
            env=umgebung,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.antworten: dict[int, dict] = {}
        threading.Thread(target=self._lesen, daemon=True).start()

    def _lesen(self) -> None:
        for zeile in self.proc.stdout:  # type: ignore[union-attr]
            zeile = zeile.strip()
            if not zeile:
                continue
            try:
                nachricht = json.loads(zeile)
            except json.JSONDecodeError:
                continue
            if "id" in nachricht:
                self.antworten[nachricht["id"]] = nachricht

    def ruf(self, nr: int, methode: str, params: dict | None = None,
            warte: float = 180.0) -> dict:
        self.proc.stdin.write(  # type: ignore[union-attr]
            json.dumps({"jsonrpc": "2.0", "id": nr, "method": methode,
                        "params": params or {}}) + "\n"
        )
        self.proc.stdin.flush()  # type: ignore[union-attr]
        ende = time.time() + warte
        while time.time() < ende:
            if nr in self.antworten:
                return self.antworten[nr]
            if self.proc.poll() is not None:
                raise AssertionError(
                    f"Sidecar beendet (Code {self.proc.returncode}) vor der "
                    f"Antwort auf {methode}"
                )
            time.sleep(0.05)
        raise TimeoutError(f"{methode} ohne Antwort")

    def beenden(self) -> int:
        self.proc.stdin.close()  # type: ignore[union-attr]
        return self.proc.wait(timeout=60)


@pytest.fixture
def sidecar(tmp_path):
    """Laufender Sidecar mit Wegwerf-APPDATA.

    Der Modell-Cache wird geteilt — sonst lädt jeder Lauf mehrere GB neu.
    """
    arbeit = tmp_path / "appdata"
    (arbeit / "Blitztext").mkdir(parents=True)
    echte = os.environ.get("APPDATA")
    if echte:
        quelle = Path(echte) / "Blitztext" / "models"
        if quelle.is_dir():
            subprocess.run(
                ["cmd", "/c", "mklink", "/J",
                 str(arbeit / "Blitztext" / "models"), str(quelle)],
                capture_output=True, check=False,
            )
    s = SidecarProzess(arbeit)
    yield s
    if s.proc.poll() is None:
        try:
            s.beenden()
        except Exception:  # noqa: BLE001 — Aufräumen darf nicht scheitern
            s.proc.kill()


def test_sidecar_startet_und_antwortet(sidecar):
    """Der Weg, den das ausgelieferte Produkt nimmt."""
    antwort = sidecar.ruf(1, "ping")

    assert antwort["result"]["ok"] is True
    assert antwort["result"]["version"], "Version fehlt in der Statusleiste"


def test_config_liefert_alle_vom_frontend_gelesenen_felder(sidecar):
    """Feld-Drift zwischen `config.get` und `useMeetingStore.Config`."""
    cfg = sidecar.ruf(2, "config.get")["result"]

    for feld in (
        "appdata", "models_dir", "meetings_dir", "db_path",
        "cuda_available", "ollama_available", "models", "audio_extensions",
        # 2026-08-05 ergänzt: die Einstellungsseite zeigte vorher den ersten
        # Listeneintrag statt der tatsächlichen Vorgabe.
        "whisper_default", "cleanup_model",
    ):
        assert feld in cfg, f"config.get liefert `{feld}` nicht"

    assert cfg["whisper_default"], "Vorgabemodell darf nicht leer sein"
    assert all({"id", "label", "hint"} <= set(m) for m in cfg["models"])


def test_settings_meldet_den_zustand_des_credential_stores(sidecar):
    s = sidecar.ruf(3, "settings.get")["result"]

    assert "hf_token_present" in s
    assert "credential_store_error" in s, (
        "ohne dieses Feld kann die Oberfläche einen gestörten "
        "Credential-Manager nicht von 'kein Token' unterscheiden"
    )


def test_warteschlange_laeuft_nach_dem_start(sidecar):
    """`recover_orphans()` + Worker-Start laufen nur über `__main__`."""
    zustand = sidecar.ruf(4, "queue.state")["result"]

    assert zustand["worker_alive"] is True
    assert set(zustand["counts"]) == {
        "queued", "running", "done", "failed", "cancelled"
    }


def test_fehlerformen_ueber_den_echten_transport(sidecar):
    assert sidecar.ruf(5, "gibt.es.nicht")["error"]["code"] == -32601
    assert sidecar.ruf(6, "meeting.get", {"quatsch": 1})["error"]["code"] == -32602
    assert sidecar.ruf(7, "meeting.get", {"id": "fehlt"})["error"]["code"] == -32002


def test_kaputte_zeile_beendet_den_sidecar_nicht(sidecar):
    """Eine unlesbare Zeile darf die Schleife nicht abreißen lassen."""
    sidecar.proc.stdin.write("{das ist kein JSON\n")
    sidecar.proc.stdin.flush()

    # Danach muss er weiter antworten.
    assert sidecar.ruf(8, "ping")["result"]["ok"] is True


def test_geschlossenes_stdin_beendet_sauber(sidecar):
    sidecar.ruf(9, "ping")

    assert sidecar.beenden() == 0, "Sidecar muss mit 0 enden, nicht abstürzen"
