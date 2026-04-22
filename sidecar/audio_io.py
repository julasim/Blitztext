"""Audio file loading for the meeting pipeline.

Thin wrapper around ``faster_whisper.audio.decode_audio`` — which already
bundles PyAV and handles the format zoo (WAV, MP3, FLAC, OGG, M4A, MP4, …)
AND resamples to 16 kHz mono float32 in one call. No need to pull librosa
or ffmpeg as separate dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


SAMPLE_RATE = 16_000


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
