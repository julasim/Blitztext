"""Parakeet TDT 0.6B v3 über onnx-asr — der schnelle zweite ASR-Pfad.

Warum neben Whisper: ~600 MB statt 3 GB, läuft auf der **CPU** schneller
als large-v3 auf der GPU (RTF ~10 gegen ~2 auf dieser Maschine), 25
europäische Sprachen. Qualität auf dem Testsatz: siehe benchmark/results.
Bewusst CPU: das CUDA-Paket von onnxruntime brächte eigene cuDNN-DLLs
neben die von torch — genau die Sorte Konflikt, die uns cu121 eingebrockt
hat. Und die Warteschlange ist ohnehin seriell.

Zwei Übersetzungsarbeiten, beide als reine Funktionen testbar:

* **Token → Wörter** (:func:`tokens_to_words`): onnx-asr liefert
  Subword-Tokens mit Startzeiten (`' G'`, `'uten'` …). Der Merger braucht
  Wörter mit Start UND Ende. Wortgrenze = Token beginnt mit Leerzeichen;
  Wortende = Start des Folgeworts, letztes Wort bekommt die Audiolänge.
* **Fenster-Naht** (:func:`stitch_windows`): FastConformer-Attention
  begrenzt die Länge eines Passes. Lange Aufnahmen laufen in Fenstern mit
  Überlappung; an der Naht gewinnt bis zur Überlappmitte das alte Fenster,
  danach das neue. Grobes, robustes Muster — kein Text-Alignment.
"""

from __future__ import annotations

import os
from typing import Callable

import numpy as np

from core.log import log

MODEL_ID = "parakeet-tdt-0.6b-v3"
_HF_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
_ONNX_NAME = "nemo-parakeet-tdt-0.6b-v3"

SAMPLE_RATE = 16_000

#: Ein Fenster je Durchlauf. 4 Minuten liegen weit unter der
#: Attention-Grenze des Modells und halten den RAM-Bedarf flach.
WINDOW_SEC = 240
OVERLAP_SEC = 8


# --- Reine Funktionen (unit-getestet, kein Modell nötig) -------------------


def tokens_to_words(
    tokens: list[str],
    timestamps: list[float],
    *,
    audio_duration: float,
    offset: float = 0.0,
) -> list[dict]:
    """Subword-Tokens mit Startzeiten → Wörter in Merger-Form.

    Rückgabeform wie ``Transcriber.transcribe_with_words``:
    ``{"t0": sek, "t1": sek, "w": wort}``.
    """
    words: list[dict] = []
    current: str = ""
    start: float = 0.0

    def _flush(end: float) -> None:
        nonlocal current
        text = current.strip()
        if text:
            words.append({"t0": offset + start, "t1": offset + end, "w": text})
        current = ""

    for token, ts in zip(tokens, timestamps):
        if token.startswith(" ") and current:
            _flush(ts)
            start = ts
        elif not current:
            start = ts
        current += token

    _flush(audio_duration)
    return words


def stitch_windows(window_words: list[list[dict]], *, step_sec: float) -> list[dict]:
    """Wortlisten überlappender Fenster zu einer zusammennähen.

    ``window_words[i]`` trägt bereits absolute Zeiten (Offset beim
    Transkribieren addiert). Schnittregel: Fenster ``i`` behält alles bis
    zur Mitte seiner Überlappung mit Fenster ``i+1``; das Folgefenster
    liefert ab dort. Wörter, die genau auf der Naht liegen, kommen aus dem
    Fenster, in dessen Hälfte ihr Start fällt — nie aus beiden.
    """
    if len(window_words) == 1:
        return window_words[0]

    overlap = WINDOW_SEC - step_sec
    stitched: list[dict] = []
    for i, words in enumerate(window_words):
        lo = 0.0 if i == 0 else i * step_sec + overlap / 2
        hi = (i + 1) * step_sec + overlap / 2 if i + 1 < len(window_words) else float("inf")
        stitched.extend(w for w in words if lo <= w["t0"] < hi)
    return stitched


# --- Modell-Wrapper ---------------------------------------------------------


def models_root() -> str:
    """Gleiche Ableitung wie core/transcription.py — eine Modellablage."""
    override = os.environ.get("BLITZTEXT_MODELS_DIR")
    if override:
        return override
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.join(appdata, "Blitztext", "models")


class ParakeetTranscriber:
    """Gleiche Oberfläche wie ``core.transcription.Transcriber``, damit die
    Pipeline per Engine-Dispatch zwischen beiden wechseln kann."""

    def __init__(self, *, language: str = "de", models_dir: str | None = None) -> None:
        self._language = language
        self._models_dir = models_dir or os.path.join(models_root(), MODEL_ID)
        self._model = None

    def load(self) -> None:
        """Modell laden; fehlende Dateien einmalig von HF holen (~600 MB).

        Danach läuft alles offline — gleiche Regel wie bei den
        Whisper-Gewichten.
        """
        if self._model is not None:
            return

        import onnx_asr

        if not os.path.isdir(self._models_dir) or not os.listdir(self._models_dir):
            log(f"parakeet: lade {_HF_REPO} nach {self._models_dir}")
            from huggingface_hub import snapshot_download

            snapshot_download(_HF_REPO, local_dir=self._models_dir)

        self._model = onnx_asr.load_model(
            _ONNX_NAME, path=self._models_dir
        ).with_timestamps()

    def transcribe_with_words(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> tuple[list[dict], dict]:
        """Voller Durchlauf, bei langen Aufnahmen in Fenstern.

        ``language`` wird ignoriert — Parakeet v3 erkennt die Sprache
        selbst (25 europäische). Die Rückgabe meldet deshalb ``language:
        "auto"``; die Pipeline übernimmt dann die Whisper-Konvention,
        nichts zu überschreiben.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if audio.size == 0:
            return [], {"language": "", "language_prob": 0.0, "duration": 0.0}

        duration = float(len(audio)) / SAMPLE_RATE
        step = WINDOW_SEC - OVERLAP_SEC

        starts = [0.0]
        while starts[-1] + WINDOW_SEC < duration:
            starts.append(starts[-1] + step)

        window_words: list[list[dict]] = []
        for i, t_start in enumerate(starts):
            lo = int(t_start * SAMPLE_RATE)
            hi = min(int((t_start + WINDOW_SEC) * SAMPLE_RATE), len(audio))
            chunk = audio[lo:hi]
            result = self._model.recognize(chunk, sample_rate=SAMPLE_RATE)
            window_words.append(
                tokens_to_words(
                    list(result.tokens),
                    list(result.timestamps),
                    audio_duration=len(chunk) / SAMPLE_RATE,
                    offset=t_start,
                )
            )
            if on_progress is not None:
                on_progress((i + 1) / len(starts))

        words = stitch_windows(window_words, step_sec=step)
        return words, {"language": "auto", "language_prob": 0.0, "duration": duration}
