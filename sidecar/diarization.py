"""pyannote.audio Wrapper — läuft mit 3.3.x **und** 4.x.

Holds a lazily-initialized pipeline, runs it on 16 kHz mono numpy audio,
and returns a flat list of ``{start, end, speaker}`` segments in seconds.

Versionsfest, weil der Umstieg auf pyannote 4 über eine **parallele venv**
gemessen wird — dieselbe Codebasis muss in beiden laufen. Die drei
Unterschiede (Modellname, token-kwarg, Ausgabeform) sind unten je an der
Stelle behandelt, an der sie auftreten.

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


SAMPLE_RATE = 16_000


def _pyannote_major() -> int:
    """Installierte pyannote.audio-Hauptversion; 3, wenn unbestimmbar."""
    try:
        from importlib.metadata import version

        return int(version("pyannote.audio").split(".")[0])
    except Exception:
        return 3


def diar_model_name() -> str:
    """Je Version das passende Modell. community-1 verlangt pyannote 4;
    umgekehrt kann 4.x das alte 3.1-Modell zwar laden, aber dann misst man
    nicht das, was man vergleichen will."""
    if _pyannote_major() >= 4:
        return "pyannote/speaker-diarization-community-1"
    return "pyannote/speaker-diarization-3.1"


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

        model = diar_model_name()
        token = _get_hf_token()
        if not token:
            raise RuntimeError(
                f"Kein HuggingFace-Token. pyannote braucht einen akzeptierten "
                f"Lizenz-Zugang zu '{model}'. Bitte Token im Keyring unter "
                f"Blitztext/hf_token ablegen oder HUGGINGFACE_HUB_TOKEN env setzen."
            )

        # pyannote 4 bringt Opt-out-Telemetrie mit, per Default AN
        # (Endpunkt otel.pyannote.ai, Session-ID je Prozess). Blitztext
        # sendet nichts nach außen — abschalten, BEVOR pyannote lädt,
        # denn das Telemetrie-Modul liest die Variable beim Import.
        # setdefault: eine bewusst gesetzte Umgebung gewinnt.
        os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

        try:
            from pyannote.audio import Pipeline  # type: ignore
        except ImportError as e:
            # Den ECHTEN Fehler mitgeben. Im gebündelten Sidecar ist pyannote
            # sehr wohl vorhanden, der Import scheitert dort aber an einem
            # Untermodul, das PyInstaller nicht erwischt hat. Eine Meldung,
            # die pauschal „ist nicht installiert" behauptet, schickt die
            # Fehlersuche dann in die völlig falsche Richtung — genau das ist
            # beim 0.2.0-Paket passiert.
            fehlend = getattr(e, "name", None)
            hinweis = f", fehlendes Modul: {fehlend}" if fehlend else ""
            raise RuntimeError(
                f"pyannote.audio konnte nicht geladen werden — "
                f"{type(e).__name__}: {e}{hinweis} "
                f"(siehe sidecar/requirements.txt)"
            ) from e

        # 3.3.x-Workaround: dortige huggingface_hub-Stände kennen das
        # use_auth_token-Weiterreichen nicht mehr; die Env-Var greift
        # immer. Unter 4.x wirkungslos, aber harmlos.
        os.environ.setdefault("HUGGINGFACE_HUB_TOKEN", token)
        os.environ.setdefault("HF_TOKEN", token)

        try:
            import torch  # type: ignore

            # 4.x heißt der kwarg `token`, 3.x `use_auth_token`. Beide
            # Richtungen über TypeError abfangen — so trägt der Code auch
            # Zwischenversionen, die keinen von beiden mögen (dann greift
            # die Env-Var von oben).
            try:
                pipeline = Pipeline.from_pretrained(model, token=token)
            except TypeError:
                try:
                    pipeline = Pipeline.from_pretrained(model, use_auth_token=token)
                except TypeError:
                    pipeline = Pipeline.from_pretrained(model)

            # Geräteswahl, versionsgekoppelt:
            # * pyannote 3.x lief auf torch 2.4+cu121 — dessen cuDNN hat
            #   unter Windows ein fehlendes Symbol (cudnnGetLibConfig), das
            #   die Inferenz aus nativem Code heraus killt, unfangbar für
            #   Python. Default dort: CPU.
            # * Unter pyannote 4 / torch 2.8+cu128 ist der Fehler behoben
            #   (verifiziert 2026-07-24: 31 s Audio in 1,9 s auf der 4060).
            #   Default dort: GPU.
            # BLITZTEXT_DIAR_CPU überstimmt in beide Richtungen.
            default_cpu = "1" if _pyannote_major() < 4 else "0"
            force_cpu = os.environ.get("BLITZTEXT_DIAR_CPU", default_cpu) == "1"
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

        segments = _extract_segments(annotation)
        segments.sort(key=lambda s: s["start"])
        return segments


def _extract_segments(output: Any) -> list[dict]:
    """Diarization-Ausgabe in unsere flache Segmentliste übersetzen.

    Drei Formen, absichtlich über die **Form** erkannt statt über die
    Versionsnummer (überlebt auch Zwischenversionen):

    * 4.x: Wrapper-Objekt mit ``.speaker_diarization`` — erst auspacken.
    * ``Annotation`` (3.x, und evtl. auch das Ausgepackte): ``itertracks``
      liefert 3-Tupel ``(turn, track, label)``.
    * Direkt iterierbar mit 2-Tupeln ``(turn, speaker)`` — die Form aus dem
      4.x-README.
    """
    if hasattr(output, "speaker_diarization"):
        output = output.speaker_diarization

    segments: list[dict] = []
    if hasattr(output, "itertracks"):
        for turn, _track, speaker in output.itertracks(yield_label=True):
            segments.append(
                {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
            )
        return segments

    for item in output:
        turn, speaker = item[0], item[-1]
        segments.append(
            {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
        )
    return segments
