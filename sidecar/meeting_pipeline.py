"""Orchestration: audio file → transcript + diarization → turns → DB.

The single entry point is :func:`run_import`. It runs the five stages
sequentially, emits progress notifications to the RPC event stream after
each stage, and returns the final meeting id.

Stages (weighting of overall progress in brackets):

    decode     [5 %]   audio_io.load_audio
    transcribe [55 %]  core.transcription.transcribe_with_words
    diarize    [30 %]  sidecar.diarization.DiarizationPipeline.diarize
    merge      [5 %]   sidecar.merger.merge
    persist    [5 %]   meeting_store writes + normalized WAV copy

On failure at any stage the meeting is left in status=``"error"`` and the
error is re-raised so the caller (the RPC method) can return a
structured JSON-RPC error to the UI.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Callable

import numpy as np

from core.transcription import Transcriber
from sidecar import audio_io, meeting_store
from sidecar.diarization import DiarizationPipeline
from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict


# --- Progress helpers ------------------------------------------------------

_STAGES = [
    ("decode", 0.05),
    ("transcribe", 0.55),
    ("diarize", 0.30),
    ("merge", 0.05),
    ("persist", 0.05),
]
_STAGE_OFFSETS = {
    name: sum(w for _, w in _STAGES[:i]) for i, (name, _) in enumerate(_STAGES)
}
_STAGE_WIDTH = dict(_STAGES)


def _emit(
    on_event: Callable[[str, dict], None] | None,
    meeting_id: str,
    stage: str,
    stage_pct: float,
    eta_sec: float | None = None,
) -> None:
    """Bridge per-stage progress to a unified 0..1 progress value."""
    if on_event is None:
        return
    stage_pct = max(0.0, min(1.0, stage_pct))
    total = _STAGE_OFFSETS[stage] + _STAGE_WIDTH[stage] * stage_pct
    on_event(
        "meeting.progress",
        {
            "meeting_id": meeting_id,
            "stage": stage,
            "pct": round(total, 3),
            "eta_sec": eta_sec,
        },
    )


# --- Model caching ---------------------------------------------------------

_transcriber_cache: dict[str, Transcriber] = {}


def _get_transcriber(model: str, language: str) -> Transcriber:
    key = f"{model}:{language}"
    t = _transcriber_cache.get(key)
    if t is None:
        t = Transcriber(model_size=model, language=language)
        t.load()
        _transcriber_cache[key] = t
    return t


def _pick_default_whisper_model() -> str:
    """``large-v3-turbo`` if CUDA, else ``medium``."""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "large-v3-turbo"
    except Exception:
        pass
    return "medium"


# --- Main entry point ------------------------------------------------------


def create_meeting_shell(
    file_path: str,
    *,
    title: str | None = None,
    language: str = "de",
    whisper_model: str | None = None,
) -> tuple[str, str]:
    """Insert an empty meeting row + return (meeting_id, resolved_model).

    Split out from :func:`run_import` so the RPC layer can insert the row
    synchronously (to return an id to the UI) and then fire off the heavy
    stages in a worker thread via :func:`run_stages`.
    """
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"Audio-Datei nicht gefunden: {file_path}")

    if whisper_model is None:
        whisper_model = _pick_default_whisper_model()

    meeting_store.init_db()
    meeting_id = meeting_store.create_meeting(
        title=title or src.stem,
        language=language,
        whisper_model=whisper_model,
        diar_model="pyannote/speaker-diarization-3.1",
        status="processing",
    )
    return meeting_id, whisper_model


def run_stages(
    meeting_id: str,
    file_path: str,
    *,
    language: str = "de",
    whisper_model: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> None:
    """Decode → transcribe → diarize → merge → persist for an existing
    meeting row. Does all the heavy lifting."""
    src = Path(file_path)
    try:
        # -- Stage: decode --------------------------------------------------
        _emit(on_event, meeting_id, "decode", 0.0)
        t0 = time.time()
        audio, duration_ms = audio_io.load_audio(str(src))
        meeting_store.set_duration(meeting_id, duration_ms)

        # Copy source next to the meeting folder for later replay / speaker
        # preview. We keep the original container, not the resampled WAV —
        # loses less info if the user ever re-exports.
        folder = meeting_store.meeting_folder(meeting_id)
        source_copy = folder / f"source{src.suffix.lower()}"
        shutil.copy2(src, source_copy)
        meeting_store.set_audio_path(meeting_id, str(source_copy))
        _emit(on_event, meeting_id, "decode", 1.0, eta_sec=time.time() - t0)

        # -- Stage: transcribe ---------------------------------------------
        _emit(on_event, meeting_id, "transcribe", 0.0)
        transcriber = _get_transcriber(whisper_model, language)
        ts_start = time.time()
        words, info = transcriber.transcribe_with_words(
            audio,
            on_progress=lambda p: _emit(
                on_event, meeting_id, "transcribe", p
            ),
        )
        if info.get("language") and info.get("language") != language:
            # Auto-detect result differs — store what Whisper actually found.
            meeting_store.set_language(meeting_id, info["language"])

        _emit(on_event, meeting_id, "transcribe", 1.0, eta_sec=time.time() - ts_start)

        # -- Stage: diarize -------------------------------------------------
        # Best-effort: if pyannote can't load (missing HF token, missing
        # license acceptance, no CUDA fallback path …) we proceed with an
        # empty segment list. The merger then produces a single "Speaker 1"
        # turn list, splitting on long pauses for readability. The user
        # gets a usable transcript instead of a hard import failure.
        _emit(on_event, meeting_id, "diarize", 0.0)
        diar_start = time.time()
        segments: list[dict] = []
        try:
            pipeline = DiarizationPipeline.instance()
            segments = pipeline.diarize(
                audio,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                on_progress=lambda p: _emit(
                    on_event, meeting_id, "diarize", p
                ),
            )
        except RuntimeError as e:
            # Surface as a non-fatal warning so the UI can show a banner.
            if on_event is not None:
                on_event(
                    "meeting.warning",
                    {
                        "meeting_id": meeting_id,
                        "stage": "diarize",
                        "message": str(e),
                        "fallback": "single_speaker",
                    },
                )
        _emit(on_event, meeting_id, "diarize", 1.0, eta_sec=time.time() - diar_start)

        # -- Stage: merge ---------------------------------------------------
        _emit(on_event, meeting_id, "merge", 0.0)
        turns, speakers = merge(words, segments)
        _emit(on_event, meeting_id, "merge", 1.0)

        # -- Stage: persist -------------------------------------------------
        _emit(on_event, meeting_id, "persist", 0.0)
        speaker_dicts = [speaker_to_store_dict(s) for s in speakers]
        meeting_store.upsert_speakers(meeting_id, speaker_dicts)
        refreshed = meeting_store.get_meeting(meeting_id)
        assert refreshed is not None
        label_to_id = {s["label"]: s["id"] for s in refreshed["speakers"]}
        turn_dicts = [turn_to_store_dict(t, label_to_id) for t in turns]
        meeting_store.upsert_turns(meeting_id, turn_dicts)
        meeting_store.set_status(meeting_id, "ready")
        _emit(on_event, meeting_id, "persist", 1.0)

        if on_event is not None:
            on_event("meeting.done", {"meeting_id": meeting_id})

    except Exception as e:
        meeting_store.set_status(meeting_id, "error")
        if on_event is not None:
            on_event(
                "meeting.error",
                {"meeting_id": meeting_id, "message": str(e)},
            )
        raise


def run_import(
    file_path: str,
    *,
    title: str | None = None,
    language: str = "de",
    whisper_model: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    on_event: Callable[[str, dict], None] | None = None,
) -> str:
    """Convenience: create the shell + run all stages synchronously.

    Used by smoke tests. The RPC layer uses ``create_meeting_shell`` +
    ``run_stages`` directly so it can thread the heavy work off.
    """
    meeting_id, model = create_meeting_shell(
        file_path, title=title, language=language, whisper_model=whisper_model
    )
    run_stages(
        meeting_id,
        file_path,
        language=language,
        whisper_model=model,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        on_event=on_event,
    )
    return meeting_id


# --- Small helper that the pipeline uses to keep the model warm -----------


def warm_models(language: str = "de") -> None:
    """Pre-load models so the first real import is fast. Optional — the
    pipeline will load them on demand otherwise."""
    _get_transcriber(_pick_default_whisper_model(), language)
    DiarizationPipeline.instance().ensure_loaded()
