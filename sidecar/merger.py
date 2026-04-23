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
    turns = _group_turns(assignments, label_map, turn_gap_ms)

    # 4) Speaker-Stats berechnen.
    speakers = _compute_speaker_stats(turns, label_map)

    return turns, speakers


# --- Einzelschritte --------------------------------------------------------


def _build_single_speaker(ws: list[Word]) -> tuple[list[Turn], list[SpeakerStats]]:
    """Fallback, wenn keine Diarization-Segments vorhanden sind."""
    if not ws:
        return [], []
    text = " ".join(w.text.strip() for w in ws if w.text.strip())
    turn = Turn(
        idx=0,
        speaker_label="Speaker 1",
        start_ms=ws[0].t0_ms,
        end_ms=ws[-1].t1_ms,
        text_raw=text,
        words=[{"t0": w.t0_ms, "t1": w.t1_ms, "w": w.text} for w in ws],
        overlap_flag=False,
    )
    total_ms = max(1, turn.end_ms - turn.start_ms)
    speaker = SpeakerStats(
        label="Speaker 1",
        color=palette_color(0),
        word_count=len(ws),
        duration_ms=total_ms,
        share_pct=100.0,
    )
    return [turn], [speaker]


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


def _group_turns(
    assignments: list[tuple[Word, str, bool]],
    label_map: dict[str, str],
    turn_gap_ms: int,
) -> list[Turn]:
    turns: list[Turn] = []
    cur_words: list[Word] = []
    cur_spk_raw: str | None = None
    cur_overlap: bool = False

    def flush() -> None:
        if not cur_words or cur_spk_raw is None:
            return
        text = " ".join(w.text.strip() for w in cur_words if w.text.strip())
        turns.append(
            Turn(
                idx=len(turns),
                speaker_label=label_map[cur_spk_raw],
                start_ms=cur_words[0].t0_ms,
                end_ms=cur_words[-1].t1_ms,
                text_raw=text,
                words=[{"t0": w.t0_ms, "t1": w.t1_ms, "w": w.text} for w in cur_words],
                overlap_flag=cur_overlap,
            )
        )

    for word, spk_raw, overlap in assignments:
        if cur_spk_raw is None:
            cur_spk_raw = spk_raw
            cur_words = [word]
            cur_overlap = overlap
            continue

        gap = word.t0_ms - cur_words[-1].t1_ms
        if spk_raw == cur_spk_raw and gap <= turn_gap_ms:
            cur_words.append(word)
            cur_overlap = cur_overlap or overlap
        else:
            flush()
            cur_spk_raw = spk_raw
            cur_words = [word]
            cur_overlap = overlap

    flush()
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
