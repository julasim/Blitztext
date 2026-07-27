"""Fachvokabular: Zusammensetzen, Kürzen, Durchreichen.

Der Wert steht und fällt damit, dass die Begriffe **ankommen** — Whisper
kürzt still auf ~224 Tokens, und ein Vokabular, das unterwegs verloren
geht, wirkt wie ein wirkungsloses Feature.
"""

from __future__ import annotations

import sidecar.methods  # noqa: F401 — registriert die @method-Handler
from sidecar.audio_io import HOTWORDS_MAX_CHARS, build_hotwords
from sidecar.rpc import call_method


# --- Zusammensetzen ---------------------------------------------------------


def test_quellen_werden_verbunden():
    hotwords, dropped = build_hotwords("PPSV, Bewehrung", "ÖNORM, OIB-Richtlinie")

    assert hotwords == "PPSV, Bewehrung, ÖNORM, OIB-Richtlinie"
    assert dropped == []


def test_zeilenumbrueche_zaehlen_wie_kommas():
    """Die Firmenliste tippt man zeilenweise, das Import-Feld eher inline."""
    hotwords, _ = build_hotwords("ÖNORM B 1801\nBewehrung\nBauklasse")

    assert hotwords == "ÖNORM B 1801, Bewehrung, Bauklasse"


def test_doppelte_begriffe_nur_einmal():
    """Steht ein Begriff in Firmenliste und Projektfeld, verschwendet er
    sonst zweimal Platz im knappen Prompt."""
    hotwords, _ = build_hotwords("ÖNORM, PPSV", "önorm, Bewehrung")

    assert hotwords == "ÖNORM, PPSV, Bewehrung"


def test_leere_quellen():
    assert build_hotwords(None, "") == ("", [])


def test_ueberfluessiger_leerraum_faellt_weg():
    hotwords, _ = build_hotwords("  PPSV  ,,   Bewehrung  ")

    assert hotwords == "PPSV, Bewehrung"


# --- Längengrenze -----------------------------------------------------------


def test_zu_lange_liste_wird_gekuerzt_und_gemeldet():
    """Der Punkt der Rückmeldung: Whisper würde still abschneiden."""
    begriffe = [f"Fachbegriff{i:03d}" for i in range(100)]

    hotwords, dropped = build_hotwords(", ".join(begriffe))

    assert len(hotwords) <= HOTWORDS_MAX_CHARS
    assert dropped, "weggefallene Begriffe müssen gemeldet werden"
    assert len(hotwords.split(", ")) + len(dropped) == len(begriffe)


def test_projektvokabular_hat_vorrang_vor_firmenliste():
    """Bei Platzmangel überlebt das Projektspezifische — die Firmenliste
    kennt das Modell aus anderen Terminen ohnehin eher."""
    projekt = "PPSV, Karl-Heinz"
    firma = ", ".join(f"Allgemeinbegriff{i:03d}" for i in range(100))

    hotwords, dropped = build_hotwords(projekt, firma)

    assert hotwords.startswith("PPSV, Karl-Heinz")
    assert all("Allgemein" in d for d in dropped)


# --- Durchreichen bis in den Job -------------------------------------------


def test_vokabular_landet_in_den_job_parametern(queue, store, tmp_path):
    """Der eigentliche Beweis: was im UI eingetippt wird, muss in
    params_json ankommen — sonst wirkt es nie."""
    from sidecar import jobs

    _q, _events, audio = queue
    store.set_setting("vocabulary", "ÖNORM, Bewehrung")

    call_method(
        "queue.enqueue", {"paths": [str(audio)], "vocabulary": "PPSV, Karl-Heinz"}
    )

    job = jobs.list_jobs()[0]
    assert job["params"]["hotwords"] == "PPSV, Karl-Heinz, ÖNORM, Bewehrung"


def test_ohne_vokabular_bleibt_das_feld_leer(queue, store):
    from sidecar import jobs

    _q, _events, audio = queue

    call_method("queue.enqueue", {"paths": [str(audio)]})

    assert jobs.list_jobs()[0]["params"]["hotwords"] is None


def test_firmenliste_ueberlebt_neustart(store):
    """settings-Tabelle statt Credential-Manager — mehrzeiliger Text
    gehört in die DB."""
    call_method("settings.set_vocabulary", {"vocabulary": "ÖNORM\nBewehrung"})
    store.close()
    store.init_db()

    assert call_method("settings.get_vocabulary")["vocabulary"] == "ÖNORM\nBewehrung"
