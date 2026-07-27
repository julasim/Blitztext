"""Kennzahlen für den Qualitätsvergleich.

Bewusst ohne ``jiwer``: WER ist Levenshtein über Wortlisten, das sind ein
paar Dutzend Zeilen. Wir wollen die Normalisierung selbst in der Hand
haben — sie entscheidet mit über die Zahl — und eine Kennzahl, an der
Umbau-Entscheidungen hängen, sollte man aufschlagen können.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict


# --- Normalisierung ---------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_de(text: str) -> str:
    """Deutsche Normalisierung für den WER-Vergleich.

    Was passiert:
    * Unicode auf NFC (damit ``ö`` und ``o+¨`` gleich zählen)
    * Kleinschreibung
    * Bindestrich → Leerzeichen: ``OIB-Richtlinie`` und ``OIB Richtlinie``
      sind dieselbe Aussage, nur andere Schreibung
    * Satzzeichen weg, Mehrfach-Leerzeichen zusammen

    Was **nicht** passiert: Zahlen bleiben, wie sie dastehen. „12" und
    „zwölf" gelten als verschieden. Bei Baukosten, Normnummern und
    Fristen ist das ein echter Fehler und kein Formatierungsdetail —
    genau dort wollen wir ihn sehen.
    """
    text = unicodedata.normalize("NFC", text or "")
    text = text.lower()
    text = text.replace("-", " ").replace("–", " ").replace("—", " ")
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def words(text: str, *, normalize: bool = True) -> list[str]:
    prepared = normalize_de(text) if normalize else (text or "").strip()
    return prepared.split() if prepared else []


# --- WER --------------------------------------------------------------------


@dataclass(frozen=True)
class WerResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int
    hypothesis_words: int

    def as_dict(self) -> dict:
        return asdict(self)


def wer(reference: str, hypothesis: str, *, normalize: bool = True) -> WerResult:
    """Word Error Rate = (S + D + I) / Wörter der Referenz.

    Klassische Levenshtein-Distanz über Wortlisten mit Rückverfolgung der
    Operationen, damit man sieht, *woraus* die Zahl besteht: viele
    Einfügungen deuten auf Halluzinationen in Stille, viele Löschungen auf
    verschluckte Passagen. Das ist der eigentliche Nutzen gegenüber einer
    nackten Prozentzahl.

    Bei leerer Referenz ist WER nicht definiert; wir geben 0.0 zurück, wenn
    auch die Hypothese leer ist, sonst 1.0.
    """
    ref = words(reference, normalize=normalize)
    hyp = words(hypothesis, normalize=normalize)

    if not ref:
        return WerResult(
            wer=0.0 if not hyp else 1.0,
            substitutions=0,
            deletions=0,
            insertions=len(hyp),
            reference_words=0,
            hypothesis_words=len(hyp),
        )

    n, m = len(ref), len(hyp)
    # d[i][j] = Distanz zwischen ref[:i] und hyp[:j]
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j

    for i in range(1, n + 1):
        ref_word = ref[i - 1]
        row, prev = d[i], d[i - 1]
        for j in range(1, m + 1):
            if ref_word == hyp[j - 1]:
                row[j] = prev[j - 1]
            else:
                row[j] = 1 + min(prev[j - 1], prev[j], row[j - 1])

    # Rückverfolgung: Operationen zählen.
    subs = dels = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and d[i][j] == d[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            subs += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1

    return WerResult(
        wer=(subs + dels + ins) / n,
        substitutions=subs,
        deletions=dels,
        insertions=ins,
        reference_words=n,
        hypothesis_words=m,
    )


# --- Sprecher ---------------------------------------------------------------


@dataclass(frozen=True)
class SpeakerResult:
    reference_count: int
    hypothesis_count: int
    difference: int
    reference_names: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LoopResult:
    """Wiederholungsschleifen — Whispers klassischer Halluzinationsfehler."""

    loops: int
    affected_words: int
    total_words: int
    ratio: float
    examples: list[tuple[str, int]]

    def as_dict(self) -> dict:
        return asdict(self)


def find_loops(text: str, *, ngram: int = 3, min_repeats: int = 3) -> LoopResult:
    """Unmittelbar wiederholte Wortfolgen zählen.

    **Braucht keine Referenz** — und ist damit die einzige Qualitätszahl,
    die auch auf unkorrigiertem Material trägt. Eine Passage wie
    „servus servus servus servus…" ist objektiv falsch, egal was
    tatsächlich gesagt wurde.

    Der Fehler entsteht, wenn Whisper mit
    ``condition_on_previous_text=True`` in eine Schleife gerät: die
    eigene Ausgabe wird zum Prompt des nächsten Fensters und verstärkt
    sich selbst. Bei schwer verständlichem Audio (Raummikrofon,
    Kreuzreden) passiert das regelmäßig.

    Erfasst zwei Formen: mehrfach wiederholte n-Gramme und einzelne
    Wörter, die ``min_repeats + 1`` mal hintereinander stehen.
    """
    w = words(text)
    examples: list[tuple[str, int]] = []
    affected = 0

    i = 0
    while i + ngram <= len(w):
        gram = w[i : i + ngram]
        repeats = 1
        j = i + ngram
        while j + ngram <= len(w) and w[j : j + ngram] == gram:
            repeats += 1
            j += ngram
        if repeats >= min_repeats:
            examples.append((" ".join(gram), repeats))
            affected += ngram * repeats
            i = j
        else:
            i += 1

    i = 0
    while i < len(w):
        j = i
        while j < len(w) and w[j] == w[i]:
            j += 1
        run = j - i
        if run > min_repeats:
            examples.append((w[i], run))
            affected += run
        i = max(j, i + 1)

    examples.sort(key=lambda e: e[1], reverse=True)
    return LoopResult(
        loops=len(examples),
        affected_words=affected,
        total_words=len(w),
        ratio=affected / len(w) if w else 0.0,
        examples=examples[:5],
    )


def compare_speakers(reference_names: list[str], hypothesis_count: int) -> SpeakerResult:
    """Erkannte gegen echte Sprecheranzahl.

    Absichtlich keine DER: eine saubere Diarization Error Rate braucht
    Referenzsegmente mit exakten Ende-Zeitstempeln. Unsere Referenz (der
    korrigierte Markdown-Export) hat nur Startzeiten — die Enden aus dem
    jeweils nächsten Start zu schätzen ergäbe eine Zahl, die nach
    Präzision aussieht und keine hat.

    Die Anzahl dagegen ist eindeutig und trifft den häufigsten Fehler in
    der Praxis: aus zwei Personen werden fünf Sprecher.
    """
    unique = sorted({n.strip() for n in reference_names if n and n.strip()})
    return SpeakerResult(
        reference_count=len(unique),
        hypothesis_count=hypothesis_count,
        difference=hypothesis_count - len(unique),
        reference_names=unique,
    )
