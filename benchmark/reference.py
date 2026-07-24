"""Liest den korrigierten Markdown-Export zurück ein.

Die Referenz ist bewusst kein eigenes Format, sondern **unser eigener
Export** (``sidecar/methods.py`` → ``_meeting_to_markdown``). Julius
korrigiert die Datei im Editor; dieser Parser holt Text und Sprecher
wieder heraus.

Vorteil: das Referenzformat kann nicht vom Produkt abdriften, und man
korrigiert, statt von null abzutippen.

Erwarteter Aufbau ab der Überschrift ``## Transkript``::

    **[00:01:05] Julius** ⚠︎ überlappende Rede

    Der Fluchtweg soll über den Osthof geführt werden.

Der Kopfbereich (Titel, Datum, Sprecherliste) wird übersprungen — er ist
Beiwerk und darf beim Korrigieren auch stehenbleiben oder verschwinden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: **[hh:mm:ss] Name** — der Overlap-Marker dahinter ist optional.
_TURN_HEADER = re.compile(
    r"^\*\*\[(?P<ts>\d{1,2}:\d{2}:\d{2})\]\s*(?P<name>.+?)\*\*\s*(?P<flag>.*)$"
)
_SECTION = re.compile(r"^##\s+(?P<title>.+?)\s*$")


@dataclass(frozen=True)
class ReferenceTurn:
    start_ms: int
    speaker: str
    text: str
    overlap: bool


@dataclass(frozen=True)
class Reference:
    turns: list[ReferenceTurn]
    path: Path | None = None

    @property
    def text(self) -> str:
        """Der gesamte gesprochene Text, für die WER-Rechnung."""
        return " ".join(t.text for t in self.turns if t.text)

    @property
    def speakers(self) -> list[str]:
        seen: list[str] = []
        for t in self.turns:
            if t.speaker not in seen:
                seen.append(t.speaker)
        return seen


def _ts_to_ms(ts: str) -> int:
    h, m, s = (int(p) for p in ts.split(":"))
    return ((h * 60 + m) * 60 + s) * 1000


def parse_reference(markdown: str, path: Path | None = None) -> Reference:
    """Turns aus einem (korrigierten) Export lesen.

    Robust gegen das, was beim Korrigieren von Hand passiert: fehlender
    Kopfbereich, zusätzliche Leerzeilen, mehrzeilige Absätze, ein
    entfernter Overlap-Marker.
    """
    turns: list[ReferenceTurn] = []
    in_transcript = False
    current: dict | None = None
    buffer: list[str] = []

    def _flush() -> None:
        nonlocal current, buffer
        if current is None:
            return
        text = " ".join(line.strip() for line in buffer if line.strip())
        turns.append(
            ReferenceTurn(
                start_ms=current["start_ms"],
                speaker=current["speaker"],
                text=text,
                overlap=current["overlap"],
            )
        )
        current, buffer = None, []

    for raw in (markdown or "").splitlines():
        line = raw.rstrip()

        section = _SECTION.match(line)
        if section:
            # "## Transkript" schaltet ein, jede andere Überschrift aus —
            # so landet die Sprecherliste im Kopf nicht im Text.
            _flush()
            in_transcript = section.group("title").strip().lower().startswith(
                "transkript"
            )
            continue

        if not in_transcript:
            continue

        header = _TURN_HEADER.match(line)
        if header:
            _flush()
            current = {
                "start_ms": _ts_to_ms(header.group("ts")),
                "speaker": header.group("name").strip(),
                "overlap": "überlappend" in header.group("flag").lower(),
            }
            continue

        if current is not None:
            buffer.append(line)

    _flush()
    return Reference(turns=turns, path=path)


def load_reference(path: str | Path) -> Reference:
    p = Path(path)
    return parse_reference(p.read_text(encoding="utf-8"), path=p)


def reference_path_for(audio: str | Path) -> Path:
    """``besprechung.mp3`` → ``besprechung.reference.md`` daneben."""
    p = Path(audio)
    return p.with_suffix("").with_name(p.stem + ".reference.md")
