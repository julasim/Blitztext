"""Fachvokabular Bauwesen — Vorschlag für die Firmenliste.

Wozu
----
Whisper schreibt Fachbegriffe falsch, wenn es sie nicht erwartet: Im
Transkript einer echten Bauberatung standen `Sikerschächte`, `Zegel`,
`Karpott` und `Fahrschirm`. Als ``hotwords`` mitgegeben, trifft das Modell
sie zuverlässig — und das wirkt sich bis ins Protokoll aus, denn was im
Transkript falsch steht, kann kein Sprachmodell mehr richtigstellen.

Die harte Grenze
----------------
faster-whisper kürzt ``hotwords`` bei ``max_length // 2`` ≈ **224 Token**
still ab. Deutsche Komposita sind teuer: `Benützungsbewilligung` kostet
sieben Token, `Wärmedämmverbundsystem` acht. Die vollständige Sammlung von
111 Begriffen wäre 444 Token — die Hälfte fiele weg, ohne dass es jemand
merkt.

``KERN`` ist deshalb eine Auswahl: 49 Begriffe, 158 Token. Der Rest bleibt
frei für das **projektbezogene Feld beim Import**, wo die Namen der
Beteiligten hingehören (sie wechseln je Projekt und wirken dort mehr).

Und die Warnung
---------------
Ein überfrachtetes Vokabular **verschlechtert** die Erkennung: Am
2026-07-27 stieg der Anteil halluzinierter Wiederholungen von 1,7 auf
5,2 %, weil das Modell vorgegebene Begriffe erzwang, die nie gefallen
waren. Wer hier ergänzt, sollte die Wirkung messen
(``benchmark/metrics.find_loops``) und nicht bloß hoffen.

Anpassen
--------
Diese Liste ist ein Vorschlag, kein Gesetz. Sie landet erst in der
Firmenliste, wenn der Nutzer sie in den Einstellungen einfügt — und ist
danach ganz normal editierbar. Wer eigene Begriffe braucht, nimmt lieber
etwas aus ``KERN`` heraus, als die Liste zu verlängern.
"""

from __future__ import annotations

#: Auswahlkriterien, in dieser Reihenfolge:
#:   1. im echten Transkript nachweislich falsch verstanden
#:   2. kommt in jeder Bauberatung vor
#:   3. token-günstig — seltene Wortungetüme kosten zu viele Plätze
KERN: tuple[str, ...] = (
    # Belegt falsch verstanden (PPSV-Besprechung, 2026-08-06)
    "Sickerschacht", "Versickerung", "Ziegel", "Carport", "Böschung",
    "Absteckplan", "Bestandsplan", "Rohdecke", "Estrich", "Attika",
    # Verfahren und Behörde
    "Bebauungsplan", "Bauverhandlung", "Einreichplanung", "Baubescheid",
    "Bauamt", "Widmung", "Auflage",
    # Vermessung und Höhen
    "Grundgrenze", "Grundstücksgrenze", "Niveau", "Gefälle", "Bezugspunkt",
    # Rohbau
    "Fundament", "Bewehrung", "Stahlbeton", "Schalung", "Mauerwerk",
    # Dach
    "Flachdach", "Dachüberstand", "Abdichtung", "Dampfsperre",
    # Bauphysik
    "Wärmebrücke", "Isokorb", "Energieausweis",
    # Entwässerung
    "Überlauf", "Drainage", "Kanalanschluss",
    # Außenanlagen
    "Stützmauer", "Zufahrt", "Stellplatz", "Schotter", "Absturzsicherung",
    # Ausführung und Vertrag
    "Abnahme", "Mängelliste", "Nachtrag", "Bautagebuch", "Gewerk",
    # Normen
    "ÖNORM", "Bauordnung",
)

#: Nicht in ``KERN``, aber gesammelt — zum Nachschlagen, wenn jemand die
#: Liste auf sein Fachgebiet zuschneiden will. **Nicht einfach anhängen:**
#: dann greift die Kürzung.
WEITERE: tuple[str, ...] = (
    # Verfahren
    "Baubewilligung", "Bauanzeige", "Baubeginnsanzeige",
    "Fertigstellungsanzeige", "Benützungsbewilligung", "Flächenwidmungsplan",
    "Bauklasse", "Baulinie", "Baufluchtlinie", "Bausachverständiger",
    "Bauverpflichtung",
    # Vermessung
    "Höhenaufmaß", "Vermessungsurkunde", "Katastralmappe", "Straßenniveau",
    "Meereshöhe", "Höhenkote",
    # Rohbau
    "Bodenplatte", "Streifenfundament", "Ringanker", "Sturz",
    "Hochlochziegel", "Aufzugsschacht", "Stiegenhaus", "Rohbaumaß",
    "Ausgleichsschicht",
    # Dach
    "Satteldach", "Pultdach", "Dampfbremse", "Gefälledämmung", "Dachhaut",
    "Spengler", "Regenrinne",
    # Bauphysik und Haustechnik
    "U-Wert", "Wärmedämmverbundsystem", "Schallschutz", "Lüftungsanlage",
    "Fußbodenheizung", "Wärmepumpe", "Installationsschacht",
    # Erschließung
    "Filterschacht", "Retentionsbecken", "Hausanschluss", "Regenwasser",
    "Schmutzwasser", "Kiesstreifen",
    # Außenanlagen
    "Böschungslinie", "Zaunsockel", "Einfahrt", "Doppelgarage",
    "Pflasterung", "Asphalt",
    # Ausführung
    "Leistungsverzeichnis", "Massenermittlung", "Gewährleistung",
    "Baubesprechung", "Örtliche Bauaufsicht", "Ausführungsplanung",
    "Polier", "Baustellenkoordinator", "Vorleistung",
    # Normen
    "OIB-Richtlinie",
)


def kern_als_text() -> str:
    """Die Kern-Auswahl in der Form, die das Vokabular-Feld erwartet."""
    return ", ".join(KERN)
