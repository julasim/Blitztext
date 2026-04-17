import io
import os
import threading
from typing import Callable, Optional

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.utils import _MODELS
from huggingface_hub import snapshot_download
from tqdm.auto import tqdm


class _ProgressTqdm(tqdm):
    """Custom tqdm that forwards aggregated progress to a callback.

    huggingface_hub creates one tqdm per file during a snapshot download,
    so we aggregate bytes across all instances via class-level counters.
    """

    _callback: Optional[Callable[[int, int, str], None]] = None
    _total_bytes: int = 0
    _done_bytes: int = 0
    _lock = threading.Lock()

    @classmethod
    def configure(cls, callback: Optional[Callable[[int, int, str], None]]) -> None:
        with cls._lock:
            cls._callback = callback
            cls._total_bytes = 0
            cls._done_bytes = 0

    def __init__(self, *args, **kwargs):
        kwargs["disable"] = False
        # Redirect tqdm's text output to an in-memory buffer (no file handle leak).
        kwargs["file"] = io.StringIO()
        super().__init__(*args, **kwargs)
        with _ProgressTqdm._lock:
            if self.total:
                _ProgressTqdm._total_bytes += self.total

    def update(self, n: int = 1) -> None:
        super().update(n)
        with _ProgressTqdm._lock:
            _ProgressTqdm._done_bytes += n
            done = _ProgressTqdm._done_bytes
            total = _ProgressTqdm._total_bytes
            cb = _ProgressTqdm._callback
        if cb is not None:
            try:
                desc = self.desc or ""
                # Shorten filenames if tqdm puts the full path in desc
                if len(desc) > 40:
                    desc = "…" + desc[-40:]
                cb(done, total, desc)
            except Exception:
                pass


class Transcriber:
    """Wraps faster-whisper for local speech-to-text."""

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

    def _is_cached(self, repo_id: str) -> bool:
        """Check whether the HF snapshot for repo_id already exists under models_dir."""
        folder = "models--" + repo_id.replace("/", "--")
        snap_dir = os.path.join(self._models_dir, folder, "snapshots")
        if not os.path.isdir(snap_dir):
            return False
        for entry in os.listdir(snap_dir):
            full = os.path.join(snap_dir, entry)
            if os.path.isdir(full) and os.listdir(full):
                return True
        return False

    def load(self, on_progress: Optional[Callable[[int, int, str], None]] = None) -> None:
        """Load the Whisper model. Downloads via huggingface_hub if needed.

        If on_progress is given and a download is required, it is called with
        (bytes_done, bytes_total, status_text) from the download thread.
        """
        repo_id = _MODELS.get(self._model_size, self._model_size)

        if on_progress is not None and not self._is_cached(repo_id):
            _ProgressTqdm.configure(on_progress)
            try:
                snapshot_download(
                    repo_id=repo_id,
                    cache_dir=self._models_dir,
                    tqdm_class=_ProgressTqdm,
                )
            finally:
                _ProgressTqdm.configure(None)

        self._model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
            download_root=self._models_dir,
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
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        return text.strip()
