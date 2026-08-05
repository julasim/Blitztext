"""Word-Timestamps + Speaker-Segments → Turns.

Das ist der Kernalgorithmus des Meeting-Modus. Wir haben zwei voneinander
unabhängige Inputs — Whisper liefert Wort-genaue Timestamps, pyannote
liefert Sprecher-Segments auf der Audio-Zeitachse — und müssen sie zu
einem Turn-per-Turn-Transkript zusammenführen.

Pipeline-Schritte (pure function, deterministisch):

1. Alle Segmente < ``min_segment_ms`` werden verworfen (pyannote erzeugt
   gelegentlich Mikro-Segmente bei Atempausen / Lauten). Die davon
   betroffenen Wörter fallen auf den nächstbesten Nachbarn.
2. Pro Wort wird das Segment mit maximalem zeitlichen Overlap gewählt.
   Overlap-Messung in Millisekunden. Bei 0 Overlap (selten, z. B. pyannote
   hat eine Lücke): wir wählen das zeitlich nächstgelegene Segment.
3. Wenn ein zweites Segment mindestens ``overlap_threshold`` des
   Best-Overlaps abdeckt, wird ``overlap_flag`` am resultierenden Turn
   gesetzt. Das ist das Signal für Kreuzreden / überlappende Sprecher.
4. Konsekutive Wörter desselben Sprechers mit Gap < ``turn_gap_ms``
   werden zu einem Turn. Größerer Gap → neuer Turn.
5. Am Ende: Speaker-Statistiken (word_count, duration_ms, share_pct).

Das Modul hat KEINE Abhängigkeit außer ``meeting_store.palette_color``
für die deterministische Farbzuordnung. Das macht es einzeln testbar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from sidecar.meeting_store import palette_color


# --- Eingangs- und Ausgangs-Shapes ----------------------------------------


@dataclass
class Word:
    """Ein Whisper-Wort mit Zeit-Fenster in Millisekunden."""
    t0_ms: int
    t1_ms: int
    text: str


@dataclass
class Segment:
    """Ein pyannote-Segment."""
    start_ms: int
    end_ms: int
    speaker: str  # z. B. "SPEAKER_00"

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass
class Turn:
    """Ein homogener Block eines einzelnen Sprechers."""
    idx: int
    speaker_label: str  # z. B. "Speaker 1"
    start_ms: int
    end_ms: int
    text_raw: str
    words: list[dict] = field(default_factory=list)  # serialized: {"t0","t1","w"}
    overlap_flag: bool = False


@dataclass
class SpeakerStats:
    label: str
    color: str
    word_count: int
    duration_ms: int
    share_pct: float


# --- Hilfsfunktionen -------------------------------------------------------


#: Satzschließende Zeichen. Bewusst rein orthografisch — der Merger kennt
#: die Sprache nicht und soll auch keine Sprachlogik bekommen.
_SENTENCE_END = ".?!…:;"

_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?…])")
_MULTI_SPACE = re.compile(r"\s{2,}")


def normalize_word_spacing(text: str) -> str:
    """Whisper-Trennartefakte im zusammengesetzten Text glätten.

    Whisper gibt Wörter einzeln aus; beim Zusammenfügen mit Leerzeichen
    entstehen Formen wie ``Karl -Heinz`` oder ``Wort , nächstes``. Das ist
    reine Kosmetik am Fließtext — **die Wort-Zeitstempel in ``Turn.words``
    bleiben unangetastet**, weil daraus später Untertitel entstehen und
    Text und Zeitachse nicht auseinanderlaufen dürfen.
    """
    if not text:
        return ""
    # Bindestrich zusammenziehen — aber nur bei EINSEITIGEM Leerzeichen:
    #   "Karl -Heinz"  → "Karl-Heinz"   (Whisper gibt "-Heinz" als Token aus)
    #   "Karl- Heinz"  → "Karl-Heinz"
    #   "Ja - also"    → bleibt          (beidseitig = Gedankenstrich)
    # Das Kriterium ist verlässlich, weil Whisper den Bindestrich am Wort
    # belässt und einen Gedankenstrich als eigenes Token ausgibt.
    text = re.sub(r"(\w)\s+-(\w)", r"\1-\2", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1-\2", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return _MULTI_SPACE.sub(" ", text).strip()


def _ends_sentence(text: str) -> bool:
    """Endet der Text auf einem satzschließenden Zeichen?

    Abschließende Anführungs- und Klammerzeichen werden übersprungen:
    ``sagte er."`` gilt als abgeschlossen.
    """
    stripped = (text or "").rstrip().rstrip("\"'»«)]}")
    return bool(stripped) and stripped[-1] in _SENTENCE_END


def _overlap_ms(a0: int, a1: int, b0: int, b1: int) -> int:
    """Dauer der zeitlichen Überlappung von [a0,a1] und [b0,b1] in ms."""
    return max(0, min(a1, b1) - max(a0, b0))


def _distance_ms(a0: int, a1: int, b0: int, b1: int) -> int:
    """Abstand zwischen zwei nicht-überlappenden Intervallen. 0 wenn sie
    sich berühren oder überlappen."""
    if b0 > a1:
        return b0 - a1
    if a0 > b1:
        return a0 - b1
    return 0


def _normalize_words(raw: Iterable[dict | Word]) -> list[Word]:
    out: list[Word] = []
    for w in raw:
        if isinstance(w, Word):
            out.append(w)
            continue
        # Flexibel: wir akzeptieren Dicts mit t0/t1/w ODER start/end/word
        # (faster-whisper liefert letzteres in Sekunden).
        if "t0_ms" in w:
            t0 = int(w["t0_ms"])
            t1 = int(w["t1_ms"])
        elif "t0" in w:
            t0 = int(float(w["t0"]) * (1000 if float(w["t0"]) < 10000 else 1))
            t1 = int(float(w["t1"]) * (1000 if float(w["t1"]) < 10000 else 1))
        else:  # faster-whisper native: start/end in seconds, word
            t0 = int(float(w["start"]) * 1000)
            t1 = int(float(w["end"]) * 1000)
        text = w.get("text") or w.get("w") or w.get("word") or ""
        out.append(Word(t0_ms=t0, t1_ms=t1, text=text))
    return out


def _normalize_segments(raw: Iterable[dict | Segment]) -> list[Segment]:
    out: list[Segment] = []
    for s in raw:
        if isinstance(s, Segment):
            out.append(s)
            continue
        if "start_ms" in s:
            t0 = int(s["start_ms"])
            t1 = int(s["end_ms"])
        else:
            t0 = int(float(s["start"]) * 1000)
            t1 = int(float(s["end"]) * 1000)
        spk = s.get("speaker") or s.get("speaker_label") or s.get("label") or "SPEAKER_00"
        out.append(Segment(start_ms=t0, end_ms=t1, speaker=spk))
    return out


# --- Hauptalgorithmus ------------------------------------------------------


def merge(
    words: Iterable[dict | Word],
    segments: Iterable[dict | Segment],
    *,
    turn_gap_ms: int = 1200,
    min_segment_ms: int = 300,
    overlap_threshold: float = 0.35,
    bridge_interjection_ms: int = 600,
    sentence_grace_ms: int = 1500,
) -> tuple[list[Turn], list[SpeakerStats]]:
    """Führe Wort-Timestamps und Sprecher-Segmente zu Turns + Speaker-Stats
    zusammen.

    Parameters
    ----------
    words:
        Whisper-Wörter. Jedes Wort braucht t0_ms/t1_ms/text (oder start/
        end/word in Sekunden — wir normalisieren).
    segments:
        pyannote-Segmente. start_ms/end_ms/speaker.
    turn_gap_ms:
        Pause zwischen Wörtern desselben Sprechers, ab der ein neuer Turn
        beginnt. Default 1.2 s — Kompromiss zwischen „kein Spam" und
        „keine gigantischen Monologblöcke".
    min_segment_ms:
        Segmente kürzer als das werden ignoriert (pyannote-Rauschen).
    overlap_threshold:
        Wenn ein zweites Segment ≥ diesen Anteil des Best-Overlaps eines
        Wortes abdeckt, gilt der Turn als Kreuzrede (overlap_flag=True).
    bridge_interjection_ms:
        Kurze Einwürfe („mhm", „ja") zerschneiden den Turn des
        Hauptsprechers nicht mehr. Ein Fremdblock unter dieser Dauer, der
        zwischen zwei Blöcken desselben Sprechers liegt, wird als eigener
        Turn ausgegeben — die umschließenden Blöcke wachsen aber zusammen.
        0 schaltet das ab.
    sentence_grace_ms:
        Endet ein Turn nur wegen ``turn_gap_ms`` (kein Sprecherwechsel)
        und trägt das letzte Wort **kein** Satzzeichen, wird bis zu dieser
        Pausenlänge nicht geschnitten. Verhindert Schnitte mitten im Satz.
        Muss > ``turn_gap_ms`` sein, um zu wirken.

    Returns
    -------
    (turns, speakers): Turn-Liste (in zeitlicher Reihenfolge, ``idx`` 0-based)
    und Sprecher-Stats (sortiert nach Sprech-Dauer, absteigend).
    """
    ws = sorted(_normalize_words(words), key=lambda w: w.t0_ms)
    segs = [s for s in _normalize_segments(segments) if s.duration_ms >= min_segment_ms]
    segs.sort(key=lambda s: s.start_ms)

    if not ws:
        return [], []
    if not segs:
        # Keine Diarization-Info — alle Wörter einem einzigen „Speaker 1" zuweisen.
        return _build_single_speaker(ws)

    # 1) Pro Wort: bestes Segment finden + Overlap-Flag setzen.
    assignments: list[tuple[Word, str, bool]] = []
    for w in ws:
        best_seg: Segment | None = None
        best_overlap = -1
        second_overlap = -1
        for s in segs:
            ov = _overlap_ms(w.t0_ms, w.t1_ms, s.start_ms, s.end_ms)
            if ov > best_overlap:
                second_overlap = best_overlap
                best_overlap = ov
                best_seg = s
            elif ov > second_overlap:
                second_overlap = ov

        if best_overlap <= 0:
            # Kein echter Overlap: nimm nächstgelegenes Segment.
            best_seg = min(
                segs,
                key=lambda s: _distance_ms(w.t0_ms, w.t1_ms, s.start_ms, s.end_ms),
            )
            overlap_flag = False
        else:
            overlap_flag = (
                second_overlap > 0
                and best_overlap > 0
                and (second_overlap / best_overlap) >= overlap_threshold
            )

        assert best_seg is not None
        assignments.append((w, best_seg.speaker, overlap_flag))

    # 2) Stabile Sprecher-Labels vergeben in der Reihenfolge des ersten
    #    Auftretens (SPEAKER_03 → "Speaker 1" wenn er zuerst spricht).
    label_map = _build_label_map(a[1] for a in assignments)

    # 3) In Turns gruppieren.
    turns = _group_turns(
        assignments,
        label_map,
        turn_gap_ms,
        bridge_interjection_ms=bridge_interjection_ms,
        sentence_grace_ms=sentence_grace_ms,
    )

    # 4) Speaker-Stats berechnen.
    speakers = _compute_speaker_stats(turns, label_map)

    return turns, speakers


# --- Einzelschritte --------------------------------------------------------


def _build_single_speaker(
    ws: list[Word], pause_split_ms: int = 2000
) -> tuple[list[Turn], list[SpeakerStats]]:
    """Fallback wenn keine Diarization-Segments vorhanden sind.

    Statt eines einzigen riesigen Turns splitten wir an Pausen
    > ``pause_split_ms`` (default 2 s) — das erzeugt natürliche Absätze
    in der UI, auch wenn alle einem ``Speaker 1`` zugeordnet sind.
    """
    if not ws:
        return [], []

    # Wörter in Pseudo-Turns gruppieren (Pause > pause_split_ms = neuer Turn).
    groups: list[list[Word]] = [[ws[0]]]
    for w in ws[1:]:
        gap = w.t0_ms - groups[-1][-1].t1_ms
        if gap > pause_split_ms:
            groups.append([w])
        else:
            groups[-1].append(w)

    turns: list[Turn] = []
    total_word_count = 0
    total_ms = 0
    for i, g in enumerate(groups):
        text = " ".join(w.text.strip() for w in g if w.text.strip())
        if not text:
            continue
        turn = Turn(
            idx=i,
            speaker_label="Speaker 1",
            start_ms=g[0].t0_ms,
            end_ms=g[-1].t1_ms,
            text_raw=normalize_word_spacing(text),
            words=[{"t0": w.t0_ms, "t1": w.t1_ms, "w": w.text} for w in g],
            overlap_flag=False,
        )
        turns.append(turn)
        total_word_count += len(g)
        total_ms += max(0, turn.end_ms - turn.start_ms)

    speaker = SpeakerStats(
        label="Speaker 1",
        color=palette_color(0),
        word_count=total_word_count,
        duration_ms=total_ms,
        share_pct=100.0,
    )
    return turns, [speaker]


def _build_label_map(pyannote_speakers: Iterable[str]) -> dict[str, str]:
    """Mappt pyannote-Labels (SPEAKER_00, SPEAKER_03, …) auf stabile,
    menschenlesbare Namen (Speaker 1, Speaker 2, …) in Reihenfolge des
    ersten Auftretens."""
    mapping: dict[str, str] = {}
    next_idx = 1
    for s in pyannote_speakers:
        if s not in mapping:
            mapping[s] = f"Speaker {next_idx}"
            next_idx += 1
    return mapping


@dataclass
class _Block:
    """Zwischenstufe: zusammenhängende Wörter eines Sprechers, noch ohne
    Turn-Nummer. Existiert, damit die Interjektions-Brücke über
    Nachbarblöcke hinwegschauen kann — in einem Einzeldurchlauf ginge das
    nicht, weil man den übernächsten Block noch nicht kennt."""

    speaker_raw: str
    words: list[Word]
    overlap: bool

    @property
    def start_ms(self) -> int:
        return self.words[0].t0_ms

    @property
    def end_ms(self) -> int:
        return self.words[-1].t1_ms

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def text(self) -> str:
        return " ".join(w.text.strip() for w in self.words if w.text.strip())


def _split_into_blocks(
    assignments: list[tuple[Word, str, bool]],
    turn_gap_ms: int,
    sentence_grace_ms: int,
) -> list[_Block]:
    """Erster Durchgang: an Sprecherwechseln und langen Pausen schneiden.

    Die Satzgrenzen-Regel greift nur bei Pausen **ohne** Sprecherwechsel:
    wer mitten im Satz kurz Luft holt, bekommt keinen neuen Absatz.
    """
    blocks: list[_Block] = []
    cur: _Block | None = None

    for word, spk_raw, overlap in assignments:
        if cur is None:
            cur = _Block(speaker_raw=spk_raw, words=[word], overlap=overlap)
            continue

        if spk_raw != cur.speaker_raw:
            blocks.append(cur)
            cur = _Block(speaker_raw=spk_raw, words=[word], overlap=overlap)
            continue

        gap = word.t0_ms - cur.words[-1].t1_ms
        limit = turn_gap_ms
        if sentence_grace_ms > turn_gap_ms and not _ends_sentence(cur.words[-1].text):
            # Satz ist noch offen — großzügigere Pausengrenze.
            limit = sentence_grace_ms

        if gap <= limit:
            cur.words.append(word)
            cur.overlap = cur.overlap or overlap
        else:
            blocks.append(cur)
            cur = _Block(speaker_raw=spk_raw, words=[word], overlap=overlap)

    if cur is not None:
        blocks.append(cur)
    return blocks


def _bridge_interjections(blocks: list[_Block], bridge_ms: int) -> list[_Block]:
    """Zweiter Durchgang: A–B–A mit kurzem B nicht als Bruch werten.

    Der Einwurf bleibt ein eigener Block (er wurde ja wirklich von jemand
    anderem gesagt) — aber die beiden A-Blöcke wachsen zusammen, damit ein
    „mhm" mitten im Satz keinen Absatzumbruch erzeugt. Die Wörter des
    Einwurfs bleiben zeitlich zwischen den A-Wörtern; nach dem Verbinden
    wird die Liste deshalb wieder nach Startzeit sortiert.
    """
    if bridge_ms <= 0 or len(blocks) < 3:
        return blocks

    out: list[_Block] = []
    interjections: list[_Block] = []
    i = 0
    while i < len(blocks):
        cur = blocks[i]
        # Passt A–B–A mit kurzem B?
        if (
            i + 2 < len(blocks)
            and blocks[i + 1].duration_ms <= bridge_ms
            and blocks[i + 2].speaker_raw == cur.speaker_raw
            and blocks[i + 1].speaker_raw != cur.speaker_raw
        ):
            merged = _Block(
                speaker_raw=cur.speaker_raw,
                words=cur.words + blocks[i + 2].words,
                overlap=cur.overlap or blocks[i + 2].overlap,
            )
            interjections.append(blocks[i + 1])
            # Der verschmolzene Block bleibt Kandidat für weitere Brücken.
            blocks = blocks[:i] + [merged] + blocks[i + 3 :]
            continue
        out.append(cur)
        i += 1

    combined = out + interjections
    combined.sort(key=lambda b: b.start_ms)
    return combined


def _group_turns(
    assignments: list[tuple[Word, str, bool]],
    label_map: dict[str, str],
    turn_gap_ms: int,
    *,
    bridge_interjection_ms: int = 0,
    sentence_grace_ms: int = 0,
) -> list[Turn]:
    blocks = _split_into_blocks(assignments, turn_gap_ms, sentence_grace_ms)
    blocks = _bridge_interjections(blocks, bridge_interjection_ms)

    turns: list[Turn] = []
    for block in blocks:
        if not block.text:
            continue
        turns.append(
            Turn(
                idx=len(turns),
                speaker_label=label_map[block.speaker_raw],
                start_ms=block.start_ms,
                end_ms=block.end_ms,
                text_raw=normalize_word_spacing(block.text),
                words=[
                    {"t0": w.t0_ms, "t1": w.t1_ms, "w": w.text} for w in block.words
                ],
                overlap_flag=block.overlap,
            )
        )
    return turns


def _compute_speaker_stats(
    turns: Sequence[Turn], label_map: dict[str, str]
) -> list[SpeakerStats]:
    per_label: dict[str, dict] = {
        label: {"word_count": 0, "duration_ms": 0} for label in label_map.values()
    }
    for t in turns:
        stats = per_label.setdefault(
            t.speaker_label, {"word_count": 0, "duration_ms": 0}
        )
        stats["word_count"] += len(t.words)
        stats["duration_ms"] += max(0, t.end_ms - t.start_ms)

    total_ms = sum(s["duration_ms"] for s in per_label.values()) or 1

    # Farben vergeben in Reihenfolge des ersten Auftretens (= stabil gegen
    # Reordering nach Dauer im Output).
    first_seen_order = list(label_map.values())  # Insertion-order
    color_map = {label: palette_color(i) for i, label in enumerate(first_seen_order)}

    speakers = [
        SpeakerStats(
            label=label,
            color=color_map[label],
            word_count=data["word_count"],
            duration_ms=data["duration_ms"],
            share_pct=round(100.0 * data["duration_ms"] / total_ms, 1),
        )
        for label, data in per_label.items()
    ]
    # Ausgabe-Sortierung: nach Sprech-Dauer absteigend (UI-freundlich).
    speakers.sort(key=lambda s: s.duration_ms, reverse=True)
    return speakers


# --- Komfort-Serialisierung für meeting_store.upsert_turns ----------------


def turn_to_store_dict(t: Turn, speaker_id_by_label: dict[str, str]) -> dict:
    """Wandelt einen ``Turn`` in das Shape, das
    ``meeting_store.upsert_turns`` erwartet. Braucht einen Mapping von
    ``speaker_label`` auf die in der DB erzeugten speaker-IDs."""
    return {
        "speaker_id": speaker_id_by_label.get(t.speaker_label),
        "idx": t.idx,
        "start_ms": t.start_ms,
        "end_ms": t.end_ms,
        "text_raw": t.text_raw,
        "words": t.words,
        "overlap_flag": t.overlap_flag,
    }


def speaker_to_store_dict(s: SpeakerStats) -> dict:
    """Shape für ``meeting_store.upsert_speakers``."""
    return {
        "label": s.label,
        "color": s.color,
        "word_count": s.word_count,
        "duration_ms": s.duration_ms,
        "share_pct": s.share_pct,
    }
