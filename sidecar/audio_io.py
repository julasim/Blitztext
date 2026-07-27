"""Audio file loading for the meeting pipeline.

Thin wrapper around ``faster_whisper.audio.decode_audio`` — which already
bundles PyAV and handles the format zoo (WAV, MP3, FLAC, OGG, M4A, MP4, …)
AND resamples to 16 kHz mono float32 in one call. No need to pull librosa
or ffmpeg as separate dependencies.

Hier steht außerdem, **welche Endungen** als Audio gelten. Eine Liste, eine
Wahrheit: der Ordner-Import filtert danach, und ``config.get`` reicht sie
an die UI durch, damit der Dateidialog nicht seine eigene Fassung pflegt.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


SAMPLE_RATE = 16_000

#: Was PyAV zuverlässig dekodiert. Kleingeschrieben, mit Punkt.
AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".m4a",
    ".m4b",
    ".flac",
    ".ogg",
    ".opus",
    ".aac",
    ".wma",
    ".mp4",
    ".mkv",
    ".webm",
)


#: Whisper kürzt den Hotword-Prompt hart auf ``max_length // 2`` Tokens
#: (~224). Wir begrenzen vorher auf Zeichen, damit wir sagen können, was
#: wegfällt — Whisper täte es still. 4 Zeichen je Token ist die grobe
#: Faustregel für deutschen Text; bewusst konservativ.
HOTWORDS_MAX_CHARS = 700


def build_hotwords(*sources: str | None) -> tuple[str, list[str]]:
    """Vokabular-Quellen zu einer Whisper-Hotword-Zeile verbinden.

    Reihenfolge ist Priorität: was zuerst kommt, überlebt die Kürzung.
    Aufrufer geben deshalb das Projektvokabular vor der Firmenliste an.

    Returns
    -------
    (hotwords, dropped)
        ``hotwords`` ist eine kommaseparierte Zeile, ``dropped`` sind die
        Begriffe, die wegen der Längengrenze weggefallen sind. Die
        Rückmeldung ist der Punkt: ein still gekürztes Vokabular ist ein
        Fehler, den niemand bemerkt.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for raw in (source or "").replace("\n", ",").split(","):
            term = " ".join(raw.split())
            if not term or term.lower() in seen:
                continue
            seen.add(term.lower())
            terms.append(term)

    kept: list[str] = []
    dropped: list[str] = []
    length = 0
    for term in terms:
        addition = len(term) + (2 if kept else 0)
        if length + addition > HOTWORDS_MAX_CHARS:
            dropped.append(term)
            continue
        kept.append(term)
        length += addition

    return ", ".join(kept), dropped


def is_supported(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AUDIO_EXTENSIONS


def expand_paths(paths: "list[str] | tuple[str, ...]") -> "tuple[list[Path], list[dict]]":
    """Dateien und Ordner zu einer Dateiliste auflösen.

    Ordner werden **rekursiv** durchsucht und alphabetisch sortiert — so ist
    die Reihenfolge in der Warteschlange vorhersagbar und entspricht dem,
    was der Explorer zeigt. Nicht unterstützte Dateien werden nicht still
    verschluckt, sondern mit Grund zurückgemeldet.

    Returns
    -------
    (files, skipped)
        ``files`` sind existierende, unterstützte Dateien ohne Duplikate.
        ``skipped`` ist eine Liste ``{path, reason}``.
    """
    files: list[Path] = []
    skipped: list[dict] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        try:
            key = p.resolve()
        except OSError:
            key = p
        if key in seen:
            skipped.append({"path": str(p), "reason": "doppelt"})
            return
        seen.add(key)
        files.append(p)

    for raw in paths:
        p = Path(raw)
        if not p.exists():
            skipped.append({"path": str(p), "reason": "nicht gefunden"})
            continue
        if p.is_dir():
            found = sorted(
                (f for f in p.rglob("*") if f.is_file() and is_supported(f)),
                key=lambda f: str(f).lower(),
            )
            if not found:
                skipped.append({"path": str(p), "reason": "keine Audiodateien im Ordner"})
            for f in found:
                _add(f)
            continue
        if not is_supported(p):
            skipped.append({"path": str(p), "reason": f"Format {p.suffix or '—'} wird nicht unterstützt"})
            continue
        _add(p)

    return files, skipped


def load_audio(path: str | Path) -> "tuple[np.ndarray, int]":
    """Decode any supported audio file to 16 kHz mono float32.

    Returns
    -------
    (audio, duration_ms) : (np.ndarray[float32], int)
    """
    # Local import so module-level import of sidecar stays cheap when no
    # audio work is being done.
    from faster_whisper.audio import decode_audio

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"audio file not found: {p}")

    audio = decode_audio(str(p), sampling_rate=SAMPLE_RATE)
    duration_ms = int(len(audio) * 1000 / SAMPLE_RATE)
    return audio, duration_ms
