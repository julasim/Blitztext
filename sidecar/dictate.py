"""Dictate-mode: short mic capture → Whisper → inject text into the
active foreground window.

This is the legacy Blitztext core feature. The new Tauri app keeps
the same UX (toggle-shortcut, no UI) but delegates to the sidecar over
RPC instead of running the whole thing in-process.

State machine:

    idle ──start()──> recording ──stop()──> processing ──> idle
                            ╰──cancel()──> idle

Distinct from :mod:`sidecar.recording` (which produces meetings):
- no DB row, no diarization, no LLM cleanup by default
- uses ``medium`` Whisper for low-latency transcription
- on stop(): transcribed text is sent to the active window via the
  legacy ``core.injector.inject_text`` (Ctrl+V paste through the
  Windows Clipboard) — same mechanism the original tray app uses

Optional cleanup-via-Ollama is wired through the existing
``core.llm.cleanup_turn`` so the dictate output gets the same
filler-word removal we use in meeting-mode, when the user asks for it.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

from core.audio import AudioRecorder
from core.transcription import Transcriber
from sidecar.rpc import emit_event


_log = logging.getLogger("sidecar.dictate")


# Dictate is short-utterance — buffer cap of 5 minutes is plenty.
MAX_DICTATE_SEC = 5 * 60


def _pick_dictate_model() -> tuple[str, str, str]:
    """Returns (model_size, device, compute_type) for dictate transcribing.

    Dictate values latency over absolute accuracy: ``medium`` on CUDA is
    near-instant for ≤30 s utterances. CPU fallback uses ``base`` since
    medium-on-CPU is too slow for an interactive workflow.
    """
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return ("medium", "cuda", "float16")
    except Exception:
        pass
    return ("base", "cpu", "int8")


_transcriber: Transcriber | None = None
_transcriber_lock = threading.Lock()


def _get_transcriber() -> Transcriber:
    """Lazy-loaded singleton — second invocation reuses the loaded model."""
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            model, device, compute_type = _pick_dictate_model()
            _log.info(
                "loading dictate transcriber (%s, %s, %s)", model, device, compute_type
            )
            t = Transcriber(
                model_size=model,
                language="de",
                device=device,
                compute_type=compute_type,
            )
            t.load()
            _transcriber = t
        return _transcriber


class DictateSession:
    """Process-wide singleton — only one dictate flow at a time."""

    _instance: "DictateSession | None" = None

    def __init__(self) -> None:
        self._recorder: AudioRecorder | None = None
        self._cleanup: bool = False
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "DictateSession":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None and self._recorder.is_recording

    def start(self, *, cleanup: bool = False) -> dict:
        with self._lock:
            if self.is_recording:
                raise RuntimeError("Dictate läuft bereits.")
            self._recorder = AudioRecorder(max_buffer_sec=MAX_DICTATE_SEC)
            self._recorder.start()
            self._cleanup = bool(cleanup)
        emit_event("dictate.started", {})
        _log.info("dictate started (cleanup=%s)", cleanup)
        return {"ok": True}

    def stop(self) -> dict:
        """Stop capturing and run the transcribe → (cleanup) → inject
        pipeline on a worker thread. RPC returns immediately."""
        with self._lock:
            if not self.is_recording or self._recorder is None:
                raise RuntimeError("Kein Dictate aktiv.")
            audio = self._recorder.stop()
            cleanup_flag = self._cleanup
            self._recorder = None

        emit_event("dictate.stopped", {"samples": int(audio.size)})
        threading.Thread(
            target=lambda: _run_pipeline(audio, cleanup_flag),
            name="dictate-pipeline",
            daemon=True,
        ).start()
        return {"ok": True, "samples": int(audio.size)}

    def cancel(self) -> dict:
        """Drop the in-flight buffer without transcribing or injecting."""
        with self._lock:
            if not self.is_recording or self._recorder is None:
                return {"ok": False, "reason": "not recording"}
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None
        emit_event("dictate.cancelled", {})
        _log.info("dictate cancelled")
        return {"ok": True}

    def toggle(self, *, cleanup: bool = False) -> dict:
        """One-call entrypoint for the global shortcut handler: starts if
        idle, stops if recording. The frontend doesn't need to track state
        — it just calls this on every press."""
        if self.is_recording:
            r = self.stop()
            return {**r, "transition": "stop"}
        r = self.start(cleanup=cleanup)
        return {**r, "transition": "start"}

    def state(self) -> dict:
        return {"is_recording": self.is_recording}


# --- Pipeline runner (worker-thread) --------------------------------------


def _run_pipeline(audio: np.ndarray, cleanup_flag: bool) -> None:
    """transcribe → optional cleanup → inject. Errors are emitted as
    `dictate.error` and never crash the thread."""
    if audio.size == 0:
        emit_event(
            "dictate.error",
            {"stage": "transcribe", "message": "Leere Aufnahme."},
        )
        return

    try:
        emit_event("dictate.transcribing", {})
        t = _get_transcriber()
        text = t.transcribe(audio).strip()
    except Exception as e:
        _log.exception("dictate transcribe failed")
        emit_event(
            "dictate.error",
            {"stage": "transcribe", "message": str(e)},
        )
        return

    if not text:
        emit_event(
            "dictate.done",
            {"text": "", "injected": False, "reason": "empty_transcript"},
        )
        return

    if cleanup_flag:
        try:
            from core.llm import cleanup_turn

            text = cleanup_turn(text).strip() or text
        except Exception as e:
            _log.warning("dictate cleanup failed (using raw text): %s", e)

    try:
        from core.injector import inject_text

        inject_text(text)
        emit_event("dictate.done", {"text": text, "injected": True})
        _log.info("dictate injected %d chars", len(text))
    except Exception as e:
        _log.exception("dictate inject failed")
        emit_event(
            "dictate.error",
            {"stage": "inject", "message": str(e), "text": text},
        )
