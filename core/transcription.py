import os
from typing import Callable, Optional

import httpx
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import _MODELS


# Essential files we need for faster-whisper to load the model
_REQUIRED_FILES = [
    "config.json",
    "model.bin",
    "tokenizer.json",
    "preprocessor_config.json",
]
# Optional files — download if present, skip quietly if 404
_OPTIONAL_FILES = [
    "vocabulary.txt",
    "vocabulary.json",
    "vocab.json",
]


class Transcriber:
    """Wraps faster-whisper for local speech-to-text with a custom downloader
    that reports real progress."""

    def __init__(self, model_size: str = "base", language: str = "de", models_dir: str | None = None):
        self._model_size = model_size
        self._language = language
        self._model: WhisperModel | None = None

        if models_dir is None:
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            self._models_dir = os.path.join(appdata, "VoiceType", "models")
        else:
            self._models_dir = models_dir
        os.makedirs(self._models_dir, exist_ok=True)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _local_model_dir(self) -> str:
        return os.path.join(self._models_dir, self._model_size)

    def _is_cached(self, repo_id: str = None) -> bool:
        """Model is cached if all required files exist with non-zero size."""
        d = self._local_model_dir()
        for f in _REQUIRED_FILES:
            p = os.path.join(d, f)
            if not os.path.isfile(p) or os.path.getsize(p) == 0:
                return False
        return True

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
        """Download each model file via direct HTTPS with streaming progress."""
        base_url = f"https://huggingface.co/{repo_id}/resolve/main"

        # Step 1: determine which files we actually need to download and their sizes
        file_list: list[tuple[str, int]] = []  # (name, size)
        for name in _REQUIRED_FILES + _OPTIONAL_FILES:
            local_path = os.path.join(local_dir, name)
            if os.path.isfile(local_path) and os.path.getsize(local_path) > 0:
                continue  # already have it
            try:
                head = httpx.head(f"{base_url}/{name}", follow_redirects=True, timeout=20)
                if head.status_code != 200:
                    if name in _REQUIRED_FILES:
                        raise RuntimeError(f"{name} nicht verfügbar (HTTP {head.status_code}).")
                    continue  # optional file not available
                size = int(head.headers.get("Content-Length", "0"))
                file_list.append((name, size))
            except httpx.HTTPError as e:
                if name in _REQUIRED_FILES:
                    raise RuntimeError(f"Verbindung zu HuggingFace fehlgeschlagen: {e}")
                continue

        total_bytes = sum(s for _, s in file_list)
        done_bytes = 0

        if on_progress is not None:
            on_progress(0, total_bytes, "Vorbereitung …")

        # Step 2: download each file with streaming
        for name, size in file_list:
            target_path = os.path.join(local_dir, name)
            tmp_path = target_path + ".part"
            try:
                with httpx.stream("GET", f"{base_url}/{name}", follow_redirects=True, timeout=60.0) as r:
                    r.raise_for_status()
                    with open(tmp_path, "wb") as f:
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
                # Atomic replace on success
                if os.path.exists(target_path):
                    os.remove(target_path)
                os.rename(tmp_path, target_path)
            except Exception:
                # Clean up the .part file on failure, then re-raise
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
                raise

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
        # beam_size=1 is near-identical to 5 in quality with VAD enabled, but faster
        segments, _info = self._model.transcribe(
            audio,
            language=lang,
            beam_size=1,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        return text.strip()
