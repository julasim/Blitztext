"""Die Struktur des Sachprotokolls — hier anpassen, nicht im Code drumherum.

Warum eine feste Vorlage
------------------------
Vorher erfand das Sprachmodell die Gliederung selbst. Das ging gut, solange
es wollte: Im Vergleich am 06.08.2026 lieferte Gemma saubere Abschnitte,
während Qwen unter denselben Vorgaben in Fließtext verfiel. Eine Struktur,
die vom Tagesform des Modells abhängt, taugt nicht für ein Dokument, das
immer gleich aussehen soll.

Jetzt gibt diese Datei die Gliederung vor. Je Rubrik geht **eine gezielte
Frage** an das Modell; die Reihenfolge und die Überschriften stehen fest.
Das hat drei Vorteile:

* Jedes Protokoll ist gleich aufgebaut — auch über Modellwechsel hinweg.
* Fokussierte Fragen liefern bessere Antworten als ein Sammelauftrag.
* Der Kopf (Datum, Dauer, Teilnehmer) entsteht **ohne** Modell und kann
  deshalb nicht erfunden werden.

Anpassen
--------
Rubrik streichen: Eintrag aus ``RUBRIKEN`` löschen.
Rubrik ergänzen: Eintrag anhängen — ``ueberschrift`` erscheint im Protokoll,
``frage`` geht an das Modell. Je konkreter die Frage, desto brauchbarer die
Antwort.
Reihenfolge ändern: Einträge umsortieren.

Eine Rubrik, zu der die Besprechung nichts hergibt, fällt weg — es steht
keine leere Überschrift im Dokument.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rubrik:
    """Ein Abschnitt des Protokolls."""

    ueberschrift: str
    frage: str


#: Die Gliederung. Reihenfolge = Reihenfolge im fertigen Protokoll.
#:
#: Zugeschnitten auf Bauberatungen: Was wurde besprochen, was wurde
#: festgelegt, was ist offen, wer macht was. Die Trennung von „Entscheidung"
#: und „offener Punkt" ist der Kern — genau daran hängt, ob man das
#: Protokoll später als Beleg heranziehen kann.
RUBRIKEN: tuple[Rubrik, ...] = (
    Rubrik(
        "Besprochene Themen",
        "Welche Sachthemen wurden behandelt? Nenne je Thema den Stand der "
        "Dinge und die genannten Fakten (Pläne, Maße, Flächen, Zuständige). "
        "Noch keine Entscheidungen und keine offenen Punkte — die kommen "
        "in eigene Abschnitte.",
    ),
    Rubrik(
        "Entscheidungen",
        "Welche Festlegungen wurden in dieser Besprechung getroffen? Nur "
        "das, worüber Einigkeit erzielt oder was ausdrücklich angeordnet "
        "wurde. Nenne je Entscheidung den Gegenstand und, sofern genannt, "
        "die Begründung. Vorschläge und Überlegungen ohne Festlegung "
        "gehören NICHT hierher.",
    ),
    Rubrik(
        "Hinweise und Vorbehalte",
        "Worauf wurde ausdrücklich hingewiesen? Nenne Warnungen, Auflagen, "
        "rechtliche oder technische Vorbehalte, genannte Risiken und "
        "Bedingungen, unter denen etwas gilt.",
    ),
    Rubrik(
        "Offene Punkte",
        "Was blieb ungeklärt? Nenne je Punkt, was fehlt und wovon die "
        "Klärung abhängt (fehlende Berechnung, ausstehende Prüfung, "
        "Entscheidung Dritter).",
    ),
    Rubrik(
        "Nächste Schritte",
        "Welche Aufgaben wurden vereinbart? Nenne je Aufgabe, WER sie "
        "übernimmt und BIS WANN, soweit im Gespräch genannt. Nenne auch "
        "vereinbarte Termine. Ist keine Person oder Frist genannt, gib die "
        "Aufgabe ohne Zuordnung an und erfinde keine.",
    ),
)

#: Rubriken, die auch dann erscheinen sollen, wenn sie leer bleiben — als
#: ausdrückliche Feststellung „hierzu nichts". Bei Entscheidungen ist das
#: sinnvoll: Ihr Fehlen ist selbst eine Information.
IMMER_ZEIGEN: frozenset[str] = frozenset({"Entscheidungen", "Offene Punkte"})

#: Text für eine Rubrik aus ``IMMER_ZEIGEN`` ohne Inhalt.
LEER_HINWEIS = "_In der Besprechung nicht behandelt._"
