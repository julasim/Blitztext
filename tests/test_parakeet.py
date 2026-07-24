"""Parakeet-Adapter: Token→Wort-Konversion und Fenster-Naht.

Beides reine Funktionen — hier liegt die eigentliche Fehlerquelle des
Adapters, nicht im ONNX-Aufruf. Das Modell selbst prüft der Benchmark.
"""

from __future__ import annotations

from core.parakeet import OVERLAP_SEC, WINDOW_SEC, stitch_windows, tokens_to_words


# --- Token → Wörter ---------------------------------------------------------


def test_leerzeichen_token_beginnt_neues_wort():
    words = tokens_to_words(
        [" G", "uten", " Mor", "gen"],
        [0.0, 0.3, 0.6, 0.8],
        audio_duration=1.5,
    )

    assert [w["w"] for w in words] == ["Guten", "Morgen"]
    assert words[0]["t0"] == 0.0
    assert words[0]["t1"] == 0.6, "Wortende = Start des Folgeworts"
    assert words[1]["t1"] == 1.5, "letztes Wort endet mit dem Audio"


def test_interpunktion_haengt_am_wort():
    """`.` und `,` kommen als eigene Tokens ohne Leerzeichen — sie gehören
    ans laufende Wort, nicht als eigenes."""
    words = tokens_to_words(
        [" Brand", "sch", "utz", ".", " Ein", "verstanden", "."],
        [0.0, 0.2, 0.4, 0.5, 1.0, 1.2, 1.6],
        audio_duration=2.0,
    )

    assert [w["w"] for w in words] == ["Brandschutz.", "Einverstanden."]


def test_erstes_token_ohne_leerzeichen():
    """Der Streamstart hat oft kein führendes Leerzeichen."""
    words = tokens_to_words(
        ["G", "uten", " Tag"],
        [0.0, 0.2, 0.5],
        audio_duration=1.0,
    )

    assert [w["w"] for w in words] == ["Guten", "Tag"]


def test_offset_verschiebt_alle_zeiten():
    words = tokens_to_words(
        [" Wort"],
        [1.0],
        audio_duration=2.0,
        offset=240.0,
    )

    assert words[0]["t0"] == 241.0
    assert words[0]["t1"] == 242.0


def test_leerer_input():
    assert tokens_to_words([], [], audio_duration=0.0) == []


def test_nur_leerzeichen_tokens_ergeben_kein_wort():
    assert tokens_to_words([" ", " "], [0.0, 0.5], audio_duration=1.0) == []


# --- Fenster-Naht -----------------------------------------------------------

STEP = WINDOW_SEC - OVERLAP_SEC


def _w(t0: float, text: str) -> dict:
    return {"t0": t0, "t1": t0 + 0.4, "w": text}


def test_einzelnes_fenster_unveraendert():
    words = [_w(1.0, "a"), _w(2.0, "b")]

    assert stitch_windows([words], step_sec=STEP) == words


def test_naht_dedupliziert_die_ueberlappung():
    """Ein Wort in der Überlappung erscheint in beiden Fenstern — es darf
    genau einmal überleben, aus dem Fenster seiner Naht-Hälfte."""
    mitte = STEP + OVERLAP_SEC / 2
    vor_naht = mitte - 1.0
    nach_naht = mitte + 1.0

    fenster_a = [_w(10.0, "früh"), _w(vor_naht, "naht-vor"), _w(nach_naht, "naht-nach")]
    fenster_b = [_w(vor_naht, "naht-vor"), _w(nach_naht, "naht-nach"), _w(400.0, "spät")]

    stitched = stitch_windows([fenster_a, fenster_b], step_sec=STEP)

    assert [w["w"] for w in stitched] == ["früh", "naht-vor", "naht-nach", "spät"]


def test_drei_fenster_bleiben_sortiert_und_vollstaendig():
    fenster = [
        [_w(5.0, "eins")],
        [_w(STEP + 20.0, "zwei")],
        [_w(2 * STEP + 20.0, "drei")],
    ]

    stitched = stitch_windows(fenster, step_sec=STEP)

    assert [w["w"] for w in stitched] == ["eins", "zwei", "drei"]


def test_naht_grenzwort_faellt_nicht_durch():
    """Ein Wort exakt auf der Nahtlinie gehört dem Folgefenster (lo <= t0)."""
    naht = STEP + OVERLAP_SEC / 2

    fenster_a = [_w(naht, "grenze")]
    fenster_b = [_w(naht, "grenze")]

    stitched = stitch_windows([fenster_a, fenster_b], step_sec=STEP)

    assert [w["w"] for w in stitched] == ["grenze"]
