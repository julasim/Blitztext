from __future__ import annotations

import os
from typing import Callable, Optional

import httpx
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import _MODELS

from core.log import log


# Core files all faster-whisper repos contain
_CORE_FILES = ["config.json", "model.bin", "tokenizer.json"]

# At least ONE of these vocabulary files must exist (different repos use
# different names: Systran uses vocabulary.txt, mobiuslabsgmbh uses vocabulary.json).
_VOCAB_FILES = ["vocabulary.txt", "vocabulary.json"]

# Nice-to-have files; download if available, skip on 404.
_OPTIONAL_FILES = ["preprocessor_config.json", "vocab.json"]

# Every file we'll try to fetch from HF (order doesn't matter for download logic,
# but model.bin is special-cased for the total-size HEAD).
_ALL_KNOWN_FILES = _CORE_FILES + _VOCAB_FILES + _OPTIONAL_FILES


class Transcriber:
    """Wraps faster-whisper for local speech-to-text with a custom downloader
    that reports real progress."""

    def __init__(self, model_size: str = "base", language: str = "de", models_dir: str | None = None):
        self._model_size = model_size
        self._language = language
        self._model: WhisperModel | None = None

        if models_dir is None:
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            self._models_dir = os.path.join(appdata, "Blitztext", "models")
        else:
            self._models_dir = models_dir
        os.makedirs(self._models_dir, exist_ok=True)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _local_model_dir(self) -> str:
        return os.path.join(self._models_dir, self._model_size)

    def _is_cached(self) -> bool:
        """Model is cached if all core files and at least one vocab file exist."""
        d = self._local_model_dir()
        for f in _CORE_FILES:
            p = os.path.join(d, f)
            if not os.path.isfile(p) or os.path.getsize(p) == 0:
                return False
        for f in _VOCAB_FILES:
            p = os.path.join(d, f)
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return True
        return False

    def load(self, on_progress: Optional[Callable[[int, int, str], None]] = None) -> None:
        """Load the Whisper model. Downloads missing files with real progress."""
        repo_id = _MODELS.get(self._model_size, self._model_size)
        local_dir = self._local_model_dir()
        os.makedirs(local_dir, exist_ok=True)

        if not self._is_cached():
            self._download_model(repo_id, local_dir, on_progress)

        # Load directly from the flat local dir — no symlinks involved
        self._model = WhisperModel(
            local_dir,
            device="cpu",
            compute_type="int8",
        )

    def _download_model(
        self,
        repo_id: str,
        local_dir: str,
        on_progress: Optional[Callable[[int, int, str], None]],
    ) -> None:
        """Download each model file via direct HTTPS with streaming progress.

        Strategy for fast, visible progress:
        - One quick HEAD on model.bin only to seed the total (it's ~99 % of size).
        - A shared httpx.Client reuses the TLS connection for all subsequent requests.
        - Streaming begins immediately → user sees MB/percent from the first chunk.
        """
        base_url = f"https://huggingface.co/{repo_id}/resolve/main"

        # Try every known file from HF. Whichever exists gets downloaded.
        # _is_cached() enforces the actual minimum set after the loop.
        # Order: model.bin first so the progress total is correct from chunk 1.
        candidates = ["model.bin"] + [f for f in _ALL_KNOWN_FILES if f != "model.bin"]

        total_bytes = 0
        done_bytes = 0

        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            # Seed total with model.bin size via a single fast HEAD
            try:
                head = client.head(f"{base_url}/model.bin")
                if head.status_code == 200:
                    total_bytes = int(head.headers.get("Content-Length", "0"))
            except httpx.HTTPError:
                pass

            if on_progress is not None:
                on_progress(0, total_bytes, "model.bin")

            for name in candidates:
                target_path = os.path.join(local_dir, name)
                if os.path.isfile(target_path) and os.path.getsize(target_path) > 0:
                    continue
                tmp_path = target_path + ".part"
                try:
                    with client.stream("GET", f"{base_url}/{name}") as r:
                        if r.status_code == 404:
                            continue  # file not in this repo — skip
                        r.raise_for_status()
                        size = int(r.headers.get("Content-Length", "0"))
                        if name != "model.bin":
                            total_bytes += size
                        with open(tmp_path, "wb") as f:
                            last_logged_mb = 0
                            for chunk in r.iter_bytes(chunk_size=256 * 1024):
                                if not chunk:
                                    continue
                                f.write(chunk)
                                done_bytes += len(chunk)
                                if on_progress is not None:
                                    try:
                                        on_progress(done_bytes, total_bytes, name)
                                    except Exception:
                                        pass
                                done_mb = done_bytes // (50 * 1024 * 1024)
                                if done_mb > last_logged_mb:
                                    last_logged_mb = done_mb
                                    log(
                                        f"Download {name}: "
                                        f"{done_bytes/1_000_000:.0f} / "
                                        f"{total_bytes/1_000_000:.0f} MB"
                                    )
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    os.rename(tmp_path, target_path)
                except Exception:
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    # Core/vocab files are verified via _is_cached() below, so
                    # we only re-raise if it's clearly a critical file.
                    if name in _CORE_FILES:
                        raise
                    # optional or vocab file failed — silently skip; validated below

        # Sanity check: must have core files + at least one vocabulary file
        if not self._is_cached():
            raise RuntimeError(
                "Modell-Dateien unvollständig. Bitte Internetverbindung prüfen "
                "und App neu starten."
            )

    def set_language(self, language: str) -> None:
        self._language = language

    def set_model(self, model_size: str) -> None:
        if model_size != self._model_size:
            self._model_size = model_size
            self._model = None

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if audio.size == 0:
            return ""

        lang = None if self._language == "auto" else self._language
        segments, _info = self._model.transcribe(
            audio,
            language=lang,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"threshold": 0.3, "min_silence_duration_ms": 500},
            # Speed tuning: skip timestamp prediction and text conditioning.
            # Both would slow inference down for ~no quality benefit in dictation.
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        return text.strip()

    def transcribe_with_words(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        on_progress: "Callable[[float], None] | None" = None,
    ) -> "tuple[list[dict], dict]":
        """Transcribe + return word-level timestamps.

        Used by the Meeting-Mode pipeline. Unlike ``transcribe()`` (which
        optimizes for dictation speed), this path enables Whisper's word
        timestamp prediction (~30 % slower inference, but required for
        merging with diarization segments).

        Parameters
        ----------
        audio:
            Mono float32 at 16 kHz (see :func:`sidecar.audio_io.load_audio`).
        language:
            Override the transcriber's default language (``"de"``, ``"en"``,
            or ``None`` for auto-detect).
        on_progress:
            Optional callback invoked with a 0.0..1.0 value as each segment
            finishes. Whisper is generator-based, so the fraction is based
            on the timestamp of the last emitted segment vs. audio duration.

        Returns
        -------
        (words, info)
            ``words`` is a list of ``{"t0": seconds, "t1": seconds, "w": text}``
            in time order. ``info`` is a small dict with ``language``,
            ``language_prob``, ``duration``.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if audio.size == 0:
            return [], {"language": "", "language_prob": 0.0, "duration": 0.0}

        lang = None if (language or self._language) == "auto" else (language or self._language)
        segments, info = self._model.transcribe(
            audio,
            language=lang,
            beam_size=5,  # better quality for meetings than dictation (=1)
            vad_filter=True,
            vad_parameters={"threshold": 0.35, "min_silence_duration_ms": 400},
            word_timestamps=True,
            condition_on_previous_text=True,
        )

        duration = float(info.duration or 0.0)
        words: list[dict] = []
        for seg in segments:
            # Each segment has .words (list[Word]). Some segments may have
            # None if VAD collapses them — skip defensively.
            for w in (seg.words or []):
                # strip() because faster-whisper prefixes words with a
                # leading space (like SentencePiece output).
                text = (w.word or "").strip()
                if not text:
                    continue
                words.append({"t0": float(w.start), "t1": float(w.end), "w": text})
            if on_progress and duration > 0:
                on_progress(min(1.0, float(seg.end) / duration))

        return words, {
            "language": info.language,
            "language_prob": float(info.language_probability or 0.0),
            "duration": duration,
        }
