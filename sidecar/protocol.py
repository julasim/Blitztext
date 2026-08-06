"""Sachprotokoll aus einem Transkript.

Warum es das gibt
-----------------
Das Wortprotokoll beantwortet die Frage „was wurde gesagt" — dafür gibt es
aber auch die Audiodatei. Gebraucht wird der **Sachverhalt**: was besprochen
wurde, worauf hingewiesen wurde, was entschieden wurde und was offen blieb.
Das ist eine Verdichtung, keine Glättung, und damit etwas anderes als
``cleanup.run`` (das Absatz für Absatz Füllwörter entfernt).

Warum zwei Stufen
-----------------
Ein einstündiges Gespräch sind rund 11.000 Wörter. Selbst wo das Kontext-
fenster reicht, fällt die Qualität mit der Eingabelänge deutlich. Deshalb:

    Turns  →  Abschnitte  →  je Abschnitt Stichpunkte  →  ein Protokoll
              (hier)          (core.llm, Stufe 1)         (core.llm, Stufe 2)

Die Abschnittsbildung in diesem Modul ist eine reine Funktion ohne LLM und
damit vollständig testbar — genau wie ``merger.py``.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

#: Obergrenze je Abschnitt in Zeichen. Bewusst konservativ: kleinere
#: Abschnitte kosten mehr LLM-Aufrufe, liefern aber verlässlichere
#: Zusammenfassungen — und ein 9B-Modell auf 8 GB VRAM hat ohnehin wenig
#: Spielraum für lange Eingaben.
MAX_ZEICHEN_JE_ABSCHNITT = 6000

#: Ein Abschnitt, der kürzer ist, wird nicht eigens zusammengefasst — dafür
#: lohnt der Aufruf nicht.
MIN_ZEICHEN_JE_ABSCHNITT = 200


def gruppiere_abschnitte(
    turns: Iterable[dict],
    *,
    max_zeichen: int = MAX_ZEICHEN_JE_ABSCHNITT,
) -> list[dict]:
    """Turns zu Abschnitten bündeln, die je in einen LLM-Aufruf passen.

    Schneidet **an Turn-Grenzen**, nie mitten in einer Wortmeldung: ein
    halber Satz im einen und die Fortsetzung im nächsten Abschnitt würde
    beide Zusammenfassungen verfälschen.

    Gibt Abschnitte mit ``start_ms``, ``end_ms`` und ``text`` zurück. Der
    Text trägt die Sprecher mit, weil „wer hat was zugesagt" für ein
    Protokoll zählt.
    """
    abschnitte: list[dict] = []
    aktuell: list[str] = []
    laenge = 0
    start_ms: int | None = None
    end_ms = 0

    def abschliessen() -> None:
        nonlocal aktuell, laenge, start_ms
        if aktuell and start_ms is not None:
            abschnitte.append(
                {
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "text": "\n\n".join(aktuell),
                }
            )
        aktuell = []
        laenge = 0
        start_ms = None

    for turn in turns:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        sprecher = turn.get("sprecher") or "Unbekannt"
        block = f"{sprecher}: {text}"

        # Passt der Turn nicht mehr rein, wird vorher abgeschlossen. Ein
        # einzelner übergroßer Turn bekommt einen eigenen Abschnitt — lieber
        # eine zu lange Eingabe als ein zerschnittener Gedanke.
        if aktuell and laenge + len(block) > max_zeichen:
            abschliessen()

        if start_ms is None:
            start_ms = int(turn.get("start_ms") or 0)
        end_ms = int(turn.get("end_ms") or end_ms)
        aktuell.append(block)
        laenge += len(block) + 2

    abschliessen()
    return abschnitte


def _zeit(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def erzeuge_protokoll(
    meeting: dict,
    *,
    model: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    max_zeichen: int = MAX_ZEICHEN_JE_ABSCHNITT,
) -> dict:
    """Vollständiger Lauf: Meeting → Protokoll.

    ``meeting`` ist die Struktur aus ``meeting_store.get_meeting``.
    ``on_progress(fertig, gesamt)`` wird nach jedem Abschnitt gerufen —
    bei einer Stunde Audio dauert der Lauf mehrere Minuten.

    Gibt ``{"protokoll", "abschnitte", "uebersprungen"}`` zurück.
    """
    from core.llm import summarize_section

    sprecher_nach_id = {s["id"]: s for s in meeting.get("speakers", [])}
    turns = []
    for t in meeting.get("turns", []):
        sp = sprecher_nach_id.get(t.get("speaker_id"))
        name = (sp.get("name") or sp.get("label")) if sp else "Unbekannt"
        turns.append(
            {
                "sprecher": name,
                # Die bereinigte Fassung bevorzugen, falls vorhanden.
                "text": t.get("text_clean") or t.get("text_raw") or "",
                "start_ms": t.get("start_ms", 0),
                "end_ms": t.get("end_ms", 0),
            }
        )

    abschnitte = gruppiere_abschnitte(turns, max_zeichen=max_zeichen)
    gesamt = len(abschnitte)

    zusammenfassungen: list[str] = []
    uebersprungen = 0
    for i, abschnitt in enumerate(abschnitte):
        if len(abschnitt["text"]) < MIN_ZEICHEN_JE_ABSCHNITT:
            uebersprungen += 1
        else:
            marke = f"[{_zeit(abschnitt['start_ms'])}–{_zeit(abschnitt['end_ms'])}]"
            ergebnis = summarize_section(abschnitt["text"], model=model)
            if ergebnis:
                zusammenfassungen.append(f"{marke}\n{ergebnis}")
            else:
                uebersprungen += 1
        if on_progress is not None:
            on_progress(i + 1, gesamt)

    if not zusammenfassungen:
        raise RuntimeError(
            "Kein Abschnitt enthielt protokollwürdigen Inhalt — "
            "ist das Transkript leer oder unbrauchbar?"
        )

    protokoll = fuelle_vorlage(
        meeting, zusammenfassungen, model=model, on_progress=on_progress,
        turns=turns,
    )
    return {
        "protokoll": protokoll,
        "abschnitte": gesamt,
        "uebersprungen": uebersprungen,
    }


def fuelle_vorlage(
    meeting: dict,
    zusammenfassungen: list[str],
    *,
    model: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    turns: list[dict] | None = None,
) -> str:
    """Die Rubriken aus ``protokoll_vorlage`` einzeln füllen und zusammensetzen.

    Ein Aufruf je Rubrik statt eines Sammelauftrags. Das kostet mehr Zeit,
    liefert aber eine Gliederung, die nicht vom Modell abhängt — und je
    Frage eine fokussierte Antwort statt eines Rundumschlags.
    """
    from core.llm import answer_section

    from sidecar.protokoll_vorlage import IMMER_ZEIGEN, LEER_HINWEIS, RUBRIKEN

    quelle = "\n\n".join(zusammenfassungen)
    teile = [_kopf_markdown(meeting)]

    for i, rubrik in enumerate(RUBRIKEN):
        inhalt = answer_section(rubrik.frage, quelle, model=model).strip()
        if not inhalt and rubrik.ueberschrift not in IMMER_ZEIGEN:
            continue
        teile.append(f"## {rubrik.ueberschrift}\n\n{inhalt or LEER_HINWEIS}")
        if on_progress is not None:
            # Zweite Phase: der Aufrufer sieht die Rubriken als Fortschritt.
            on_progress(i + 1, len(RUBRIKEN))

    # Deterministischer Anhang zum Schluss — ohne Sprachmodell, damit es
    # eine Gegenprobe zu den Zahlen in den Rubriken gibt.
    if turns:
        anhang = _zahlen_markdown(sammle_zahlen(turns))
        if anhang:
            teile.append(anhang)

    return "\n\n".join(teile) + "\n"


#: Einheiten, die in einer Bauberatung zählen. Ein Wert ohne Einheit ist
#: für den Anhang wertlos ("die 20" hilft niemandem), deshalb wird nur
#: aufgenommen, was eine davon trägt.
_EINHEITEN = (
    r"m²|qm|Quadratmeter|"
    r"cm|mm|Zentimeter|Millimeter|Meter|(?<![A-Za-zÄÖÜäöü])m(?![A-Za-zÄÖÜäöü²])|"
    r"%|Prozent|"
    r"Euro|€|"
    r"Kubik|m³"
)

#: Zahl (auch mit Komma oder Tausenderpunkt) direkt vor einer Einheit.
#:
#: Am Ende steht bewusst KEIN ``\b``: hinter einem Symbol wie ``%`` oder ``€``
#: gibt es keine Wortgrenze, und „mit 2 % Gefälle" fiele damit durchs Raster.
#: Der negative Lookahead leistet dasselbe für Buchstaben-Einheiten, ohne
#: Symbole auszuschließen (verhindert etwa „2 Meterware" als Treffer).
_ZAHL_MIT_EINHEIT = re.compile(
    rf"\b(\d+(?:[.,]\d+)*)\s*({_EINHEITEN})(?![A-Za-zÄÖÜäöü])"
)


def sammle_zahlen(turns: Iterable[dict]) -> list[dict]:
    """Alle Zahlenangaben mit Einheit — **ohne** Sprachmodell.

    Der Anhang, den dieses Ergebnis speist, ist die Gegenprobe zum
    Protokoll: Die Modelle verrechnen sich (aus 181 m² wurde 180, aus
    30 m² wurde 10). Was hier steht, ist dagegen unverändert aus dem
    Transkript kopiert und mit Zeitmarke belegt — man kann also in der
    Audiodatei nachhören.

    Doppelte Angaben werden zusammengefasst; die früheste Zeitmarke bleibt.
    """
    gefunden: dict[tuple[str, str], dict] = {}
    for turn in turns:
        text = turn.get("text") or ""
        for treffer in _ZAHL_MIT_EINHEIT.finditer(text):
            wert, einheit = treffer.group(1), treffer.group(2)
            schluessel = (wert.replace(".", ","), einheit.lower())
            if schluessel in gefunden:
                gefunden[schluessel]["anzahl"] += 1
                continue
            # Etwas Kontext mitgeben, sonst ist "20 cm" nicht einzuordnen.
            von = max(0, treffer.start() - 60)
            bis = min(len(text), treffer.end() + 60)
            gefunden[schluessel] = {
                "wert": wert,
                "einheit": einheit,
                "start_ms": int(turn.get("start_ms") or 0),
                "kontext": " ".join(text[von:bis].split()),
                "anzahl": 1,
            }
    return sorted(gefunden.values(), key=lambda z: z["start_ms"])


def _zahlen_markdown(zahlen: list[dict], grenze: int = 40) -> str:
    """Der Anhang. Leer, wenn nichts gefunden wurde."""
    if not zahlen:
        return ""
    zeilen = [
        "## Anhang: genannte Zahlen",
        "",
        "Unverändert aus dem Transkript übernommen, mit Zeitmarke zum "
        "Nachhören. Diese Liste entsteht **ohne** Sprachmodell und dient "
        "als Gegenprobe zu den Angaben oben.",
        "",
        "| Zeit | Wert | Zusammenhang |",
        "|---|---|---|",
    ]
    for z in zahlen[:grenze]:
        kontext = z["kontext"].replace("|", "/")
        if len(kontext) > 90:
            kontext = kontext[:87] + "…"
        zeilen.append(
            f"| {_zeit(z['start_ms'])} | {z['wert']} {z['einheit']} | …{kontext}… |"
        )
    if len(zahlen) > grenze:
        zeilen.append("")
        zeilen.append(f"_… und {len(zahlen) - grenze} weitere._")
    return "\n".join(zeilen)


def _kopf_markdown(meeting: dict) -> str:
    """Kopfzeilen des Protokolls — **ohne** Sprachmodell.

    Titel, Datum, Dauer und Teilnehmer stehen in der Datenbank. Sie durch
    ein Modell laufen zu lassen hieße nur, ihm Gelegenheit zu geben, sie
    falsch abzuschreiben.
    """
    titel = meeting.get("title") or "Besprechung"
    zeilen = [f"# Protokoll — {titel}", ""]

    angaben: list[str] = []
    if roh := meeting.get("created_at"):
        angaben.append(f"**Datum:** {_datum_lesbar(roh)}")
    dauer = int(meeting.get("duration_ms") or 0)
    if dauer:
        angaben.append(f"**Dauer:** {dauer // 60000} Minuten")
    namen = [s.get("name") for s in meeting.get("speakers", []) if s.get("name")]
    if namen:
        angaben.append(f"**Teilnehmer:** {', '.join(namen)}")
    else:
        anzahl = len(meeting.get("speakers", []))
        if anzahl:
            angaben.append(f"**Sprecher:** {anzahl} (nicht benannt)")

    zeilen.extend(angaben)
    zeilen.append("")
    zeilen.append(
        "> Maschinell aus der Tonaufnahme erstellt. **Zahlen, Maße und "
        "Fristen vor der Verwendung gegenlesen.**"
    )
    return "\n".join(zeilen)


def _datum_lesbar(iso: str) -> str:
    """`2026-08-06T05:24:38Z` → `06.08.2026, 05:24`."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return dt.strftime("%d.%m.%Y, %H:%M")


def _kopfzeilen(meeting: dict) -> str:
    """Bekannte Eckdaten, damit das Modell sie nicht erfinden muss."""
    zeilen = [f"Titel: {meeting.get('title') or '—'}"]
    if meeting.get("created_at"):
        zeilen.append(f"Datum: {meeting['created_at']}")
    dauer = int(meeting.get("duration_ms") or 0)
    if dauer:
        zeilen.append(f"Dauer: {dauer // 60000} Minuten")
    namen = [
        s.get("name")
        for s in meeting.get("speakers", [])
        if s.get("name")
    ]
    if namen:
        zeilen.append(f"Benannte Teilnehmer: {', '.join(namen)}")
    return "\n".join(zeilen)
