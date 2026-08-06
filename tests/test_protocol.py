"""Abschnittsbildung fürs Sachprotokoll — die Logik ohne LLM.

Der teure Teil (die Zusammenfassung) hängt an Ollama und ist entsprechend
markiert. Die Abschnittsbildung ist eine reine Funktion und gehört deshalb
in den Standardlauf: Sie entscheidet, was das Modell überhaupt zu sehen
bekommt, und ein Schnitt mitten in einer Wortmeldung verfälscht zwei
Zusammenfassungen auf einmal.
"""

from __future__ import annotations

from sidecar.protocol import _kopf_markdown, gruppiere_abschnitte, sammle_zahlen


def _turn(sprecher: str, text: str, start: int, ende: int) -> dict:
    return {"sprecher": sprecher, "text": text, "start_ms": start, "end_ms": ende}


def test_kurzes_gespraech_bleibt_ein_abschnitt():
    turns = [
        _turn("Julius", "Wir beginnen mit dem Brandschutz.", 0, 3000),
        _turn("Bauherr", "Passt.", 3000, 4000),
    ]

    abschnitte = gruppiere_abschnitte(turns)

    assert len(abschnitte) == 1
    assert abschnitte[0]["start_ms"] == 0
    assert abschnitte[0]["end_ms"] == 4000


def test_sprecher_stehen_im_text():
    """Für ein Protokoll zählt, wer etwas zugesagt hat."""
    turns = [_turn("Julius", "Ich schicke den Plan.", 0, 2000)]

    text = gruppiere_abschnitte(turns)[0]["text"]

    assert text.startswith("Julius: ")
    assert "Ich schicke den Plan." in text


def test_langes_gespraech_wird_geteilt():
    turns = [
        _turn("A", "Wort " * 100, i * 10_000, (i + 1) * 10_000) for i in range(20)
    ]

    abschnitte = gruppiere_abschnitte(turns, max_zeichen=2000)

    assert len(abschnitte) > 1
    assert all(len(a["text"]) <= 2600 for a in abschnitte), (
        "Abschnitte dürfen die Grenze nur um den letzten Turn überschreiten"
    )


def test_es_wird_nie_mitten_in_einem_turn_geschnitten():
    """Ein halber Satz hier, die Fortsetzung dort — das würde beide
    Zusammenfassungen verfälschen."""
    turns = [
        _turn("A", "Erster Beitrag über den Bebauungsplan.", 0, 5000),
        _turn("B", "Zweiter Beitrag über die Entwässerung.", 5000, 10_000),
        _turn("A", "Dritter Beitrag über das Carport.", 10_000, 15_000),
    ]

    abschnitte = gruppiere_abschnitte(turns, max_zeichen=50)

    for a in abschnitte:
        for block in a["text"].split("\n\n"):
            sprecher, _, satz = block.partition(": ")
            assert sprecher in {"A", "B"}
            assert satz.endswith("."), f"angeschnittener Turn: {satz!r}"


def test_uebergrosser_turn_bekommt_einen_eigenen_abschnitt():
    """Ein Monolog über der Grenze wird nicht zerschnitten, sondern läuft
    als eigener Abschnitt — lieber eine lange Eingabe als ein zerrissener
    Gedanke."""
    turns = [
        _turn("A", "kurz", 0, 1000),
        _turn("B", "sehr lang " * 500, 1000, 60_000),
        _turn("A", "wieder kurz", 60_000, 61_000),
    ]

    abschnitte = gruppiere_abschnitte(turns, max_zeichen=1000)

    monolog = [a for a in abschnitte if "sehr lang" in a["text"]]
    assert len(monolog) == 1, "der lange Turn darf nicht verteilt werden"


def test_leere_turns_werden_uebersprungen():
    turns = [
        _turn("A", "", 0, 1000),
        _turn("B", "   ", 1000, 2000),
        _turn("A", "Echter Inhalt.", 2000, 3000),
    ]

    abschnitte = gruppiere_abschnitte(turns)

    assert len(abschnitte) == 1
    assert "Echter Inhalt." in abschnitte[0]["text"]
    assert abschnitte[0]["text"].count(":") == 1


def test_ohne_turns_kein_abschnitt():
    assert gruppiere_abschnitte([]) == []


def test_zeitmarken_umfassen_den_ganzen_abschnitt():
    turns = [
        _turn("A", "eins", 1000, 2000),
        _turn("B", "zwei", 5000, 9000),
    ]

    a = gruppiere_abschnitte(turns)[0]

    assert a["start_ms"] == 1000
    assert a["end_ms"] == 9000


# --- Deterministische Teile: Kopf und Zahlen-Anhang ------------------------
#
# Beide entstehen OHNE Sprachmodell. Das ist der Kern der Vorlage: Was das
# Modell nie zu sehen bekommt, kann es auch nicht verdrehen. Am 06.08.2026
# hat Gemma aus 181 m² eine 180 gemacht und Qwen aus 30 m² eine 10 — der
# Anhang ist die Gegenprobe dazu.


def test_zahlen_werden_woertlich_uebernommen():
    turns = [
        {"text": "Wir haben 181 Quadratmeter versiegelte Fläche.", "start_ms": 1_400_000},
        {"text": "Das sind 30 Quadratmeter, die wegfallen.", "start_ms": 2_195_000},
    ]

    zahlen = sammle_zahlen(turns)

    werte = [(z["wert"], z["einheit"]) for z in zahlen]
    assert ("181", "Quadratmeter") in werte
    assert ("30", "Quadratmeter") in werte


def test_prozentangaben_werden_erfasst():
    """Hinter `%` gibt es keine Wortgrenze — eine abschließende
    Wortgrenzen-Prüfung im Muster hätte alle Gefälleangaben verschluckt."""
    zahlen = sammle_zahlen([{"text": "Wir fahren mit 2 % rein.", "start_ms": 0}])

    assert [(z["wert"], z["einheit"]) for z in zahlen] == [("2", "%")]


def test_zahl_ohne_einheit_wird_ignoriert():
    """„und da 393" hilft in einem Protokoll niemandem."""
    zahlen = sammle_zahlen([{"text": "Und da 393 und dann weiter.", "start_ms": 0}])

    assert zahlen == []


def test_einheit_als_wortteil_ist_kein_treffer():
    zahlen = sammle_zahlen([{"text": "Er hat 3 Meterware gekauft.", "start_ms": 0}])

    assert zahlen == []


def test_tausenderpunkt_bleibt_erhalten():
    zahlen = sammle_zahlen([{"text": "Strafen bis 13.000 Euro.", "start_ms": 0}])

    assert zahlen[0]["wert"] == "13.000"


def test_wiederholte_angabe_wird_gezaehlt_nicht_gedoppelt():
    turns = [
        {"text": "Die Höhe ist 2,82 Meter.", "start_ms": 1000},
        {"text": "Nochmal: 2,82 Meter.", "start_ms": 90_000},
    ]

    zahlen = sammle_zahlen(turns)

    assert len(zahlen) == 1
    assert zahlen[0]["anzahl"] == 2
    assert zahlen[0]["start_ms"] == 1000, "die früheste Zeitmarke bleibt"


def test_kopf_entsteht_ohne_modell():
    """Titel, Datum, Dauer und Teilnehmer stehen in der Datenbank — sie
    durch ein Modell zu schicken hieße nur, ihm Gelegenheit zu geben, sie
    falsch abzuschreiben."""
    kopf = _kopf_markdown(
        {
            "title": "Bauberatung Musterweg",
            "created_at": "2026-08-06T05:24:38Z",
            "duration_ms": 4_152_000,
            "speakers": [{"name": "Emmanuel Sima"}, {"label": "Speaker 2"}],
        }
    )

    assert "# Protokoll — Bauberatung Musterweg" in kopf
    assert "06.08.2026" in kopf
    assert "69 Minuten" in kopf
    assert "Emmanuel Sima" in kopf
    assert "gegenlesen" in kopf, "der Warnhinweis gehört fest dazu"


def test_kopf_ohne_benannte_sprecher():
    kopf = _kopf_markdown(
        {"title": "Ohne Namen", "speakers": [{"label": "Speaker 1"}, {"label": "Speaker 2"}]}
    )

    assert "2 (nicht benannt)" in kopf
