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
    """Try keyring first, then env. Returns ``None`` if neither is set.

    Service name matches the legacy Blitztext (capital B) so we share the
    Windows Credential Manager namespace with the existing app — one
    place for all Blitztext secrets.
    """
    try:
        import keyring

        # Primary: legacy-compatible service name.
        tok = keyring.get_password("Blitztext", "hf_token")
        if tok:
            return tok
        # Tolerate older code paths that wrote lowercase.
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

        # Newer huggingface_hub releases dropped the 'use_auth_token' kwarg
        # but pyannote 3.3.x still tries to pass it through. Easiest robust
        # fix: set the env var that hf_hub_download honours automatically.
        os.environ.setdefault("HUGGINGFACE_HUB_TOKEN", token)
        os.environ.setdefault("HF_TOKEN", token)

        try:
            import torch  # type: ignore

            try:
                pipeline = Pipeline.from_pretrained(DIAR_MODEL, use_auth_token=token)
            except TypeError:
                # pyannote tries to forward use_auth_token to a function
                # that no longer accepts it — call without and rely on env.
                pipeline = Pipeline.from_pretrained(DIAR_MODEL)

            # Decide device. Default: CUDA when available, but allow an
            # opt-out via BLITZTEXT_DIAR_CPU=1 because torch+cu121's bundled
            # cuDNN on Windows has a missing symbol (cudnnGetLibConfig)
            # that crashes pyannote inference unrecoverably (the error is
            # logged from native code and kills the process before Python
            # can catch it). CPU is slower but reliable. Whisper keeps GPU.
            force_cpu = os.environ.get("BLITZTEXT_DIAR_CPU", "1") == "1"
            if torch.cuda.is_available() and not force_cpu:
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

        tensor = torch.from_numpy(audio).unsqueeze(0)
        audio_input_cuda = {
            "waveform": tensor.to(self._device),
            "sample_rate": SAMPLE_RATE,
        }

        if on_progress:
            on_progress(0.02)

        kw: dict = {}
        if min_speakers is not None:
            kw["min_speakers"] = int(min_speakers)
        if max_speakers is not None:
            kw["max_speakers"] = int(max_speakers)

        try:
            annotation = self._pipeline(audio_input_cuda, **kw)
        except (RuntimeError, OSError) as e:
            # CUDA/cuDNN mismatches on Windows commonly fail with messages
            # like "Could not load symbol cudnnGetLibConfig". Fall back to
            # CPU automatically — slower but always works. Whisper keeps its
            # GPU acceleration; only diarization is downgraded.
            msg = str(e).lower()
            cuda_hint = any(
                k in msg for k in ("cudnn", "cuda", "cublas", "cusparse", "could not load symbol")
            )
            if not cuda_hint or self._device == "cpu":
                raise
            try:
                from core.log import log

                log(f"Diarization CUDA failed ({e}); retrying on CPU.")
            except Exception:
                pass
            self._pipeline.to(torch.device("cpu"))
            self._device = "cpu"
            audio_input_cpu = {
                "waveform": tensor.to("cpu"),
                "sample_rate": SAMPLE_RATE,
            }
            annotation = self._pipeline(audio_input_cpu, **kw)

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
