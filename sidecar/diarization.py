"""pyannote.audio 3.x Wrapper.

Holds a lazily-initialized pipeline, runs it on 16 kHz mono numpy audio,
and returns a flat list of ``{start, end, speaker}`` segments in seconds.

Design notes
------------
* The pyannote pipeline is expensive to construct (~3 s on GPU, much more
  on CPU) because it lazy-loads the HuggingFace model on first use. We
  cache one instance per process.
* Windows + CUDA: pyannote requires ``torch`` with a matching CUDA build.
  We prefer CUDA if ``torch.cuda.is_available()`` and fall back to CPU
  with a warning. A long CPU run is slow but functional.
* HF token lives in the Windows keyring under ``blitztext / hf_token`` —
  the Settings UI is expected to write it there. We fall back to
  ``HUGGINGFACE_HUB_TOKEN`` env var for dev/CI.
* Failures to load the pipeline are re-raised as ``RuntimeError`` with a
  human-readable message — the RPC layer surfaces that to the UI.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import numpy as np


DIAR_MODEL = "pyannote/speaker-diarization-3.1"
SAMPLE_RATE = 16_000


# -- HF token ---------------------------------------------------------------


def _get_hf_token() -> str | None:
    """Try keyring first, then env. Returns ``None`` if neither is set."""
    try:
        import keyring

        tok = keyring.get_password("blitztext", "hf_token")
        if tok:
            return tok
    except Exception:
        pass
    return os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")


# -- Pipeline cache ---------------------------------------------------------


class DiarizationPipeline:
    """Singleton wrapper around pyannote's speaker-diarization pipeline."""

    _instance: "DiarizationPipeline | None" = None

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._device: str = "cpu"

    @classmethod
    def instance(cls) -> "DiarizationPipeline":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def ensure_loaded(self) -> None:
        """Load the pipeline on first use. Raises RuntimeError on failure."""
        if self._pipeline is not None:
            return

        token = _get_hf_token()
        if not token:
            raise RuntimeError(
                "Kein HuggingFace-Token. pyannote 3.x braucht einen "
                "akzeptierten Lizenz-Zugang zu 'pyannote/speaker-diarization-3.1' "
                "und 'pyannote/segmentation-3.0'. Bitte Token im Keyring unter "
                "blitztext/hf_token ablegen oder HUGGINGFACE_HUB_TOKEN env setzen."
            )

        try:
            from pyannote.audio import Pipeline  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "pyannote.audio ist nicht installiert. "
                "pip install 'pyannote.audio==3.3.*'"
            ) from e

        try:
            import torch  # type: ignore

            pipeline = Pipeline.from_pretrained(DIAR_MODEL, use_auth_token=token)
            if torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))
                self._device = "cuda"
            else:
                self._device = "cpu"
        except Exception as e:
            raise RuntimeError(f"Diarization-Modell konnte nicht geladen werden: {e}") from e

        self._pipeline = pipeline

    @property
    def device(self) -> str:
        return self._device

    def diarize(
        self,
        audio: np.ndarray,
        *,
        min_speakers: int | None = None,
        max_speakers: int | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> list[dict]:
        """Run diarization on 16 kHz mono float32 audio.

        Parameters
        ----------
        audio:
            Mono float32 at 16 kHz (matches :func:`sidecar.audio_io.load_audio`).
        min_speakers, max_speakers:
            Optional hints — pyannote performs much better when the speaker
            count is bounded. For a 2-person interview we pass (2, 2).
        on_progress:
            Optional 0..1 callback. pyannote doesn't expose fine-grained
            progress, so we call it once at start and once at end; the
            pipeline layer above can interpolate if it wants a smoother bar.

        Returns
        -------
        List of ``{"start": seconds, "end": seconds, "speaker": "SPEAKER_XX"}``
        in chronological order.
        """
        self.ensure_loaded()
        assert self._pipeline is not None
        if audio.size == 0:
            return []

        # pyannote wants torch tensor of shape (channels, samples). 16k mono.
        import torch  # type: ignore

        tensor = torch.from_numpy(audio).unsqueeze(0).to(self._device)
        audio_input = {"waveform": tensor, "sample_rate": SAMPLE_RATE}

        if on_progress:
            on_progress(0.02)

        kw: dict = {}
        if min_speakers is not None:
            kw["min_speakers"] = int(min_speakers)
        if max_speakers is not None:
            kw["max_speakers"] = int(max_speakers)

        annotation = self._pipeline(audio_input, **kw)

        if on_progress:
            on_progress(1.0)

        segments: list[dict] = []
        for turn, _track, speaker in annotation.itertracks(yield_label=True):
            segments.append(
                {
                    "start": float(turn.start),
                    "end": float(turn.end),
                    "speaker": str(speaker),
                }
            )
        segments.sort(key=lambda s: s["start"])
        return segments
