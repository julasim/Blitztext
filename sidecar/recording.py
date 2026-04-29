"""Live mic recording for the meeting pipeline.

A singleton ``RecordingSession`` wraps :class:`core.audio.AudioRecorder`,
inserts a meeting row up front so the UI gets an id immediately, and on
stop saves the captured PCM to a 16 kHz mono WAV next to the meeting and
hands it off to the existing offline pipeline (decode → transcribe →
diarize → merge → persist).

State machine:

    idle ──start()──> recording ──stop()──> processing
                              ╰─cancel()──> idle  (meeting deleted)

We emit ``recording.started``, ``recording.stopped``, ``recording.cancelled``
events so the UI can drive its mini-widget without polling. The follow-up
``meeting.progress`` / ``meeting.done`` events from the pipeline carry the
same ``meeting_id``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from core.audio import AudioRecorder
from sidecar import meeting_store
from sidecar.meeting_pipeline import _pick_default_whisper_model, run_stages
from sidecar.rpc import emit_event


_log = logging.getLogger("sidecar.recording")


# 2 hours hard cap on the audio buffer — matches the AudioRecorder's
# self-defense limit. Above that we'd want streaming-to-disk; until then,
# this catches "user forgot to press stop" without OOMing the process.
MAX_RECORDING_SEC = 2 * 60 * 60


class RecordingSession:
    """Process-wide singleton — only one mic capture at a time."""

    _instance: "RecordingSession | None" = None

    def __init__(self) -> None:
        self._recorder: AudioRecorder | None = None
        self._meeting_id: str | None = None
        self._title: str | None = None
        self._language: str = "de"
        self._whisper_model: str | None = None
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "RecordingSession":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_recording(self) -> bool:
        return self._recorder is not None and self._recorder.is_recording

    @property
    def is_paused(self) -> bool:
        return self._recorder is not None and self._recorder.is_paused

    # --- API exposed by the methods.py wrappers -------------------------

    def start(
        self,
        *,
        title: str | None = None,
        language: str = "de",
        whisper_model: str | None = None,
    ) -> dict:
        with self._lock:
            if self.is_recording:
                raise RuntimeError("Es läuft bereits eine Aufnahme.")

            meeting_store.init_db()
            display_title = (title or "").strip() or "Live-Aufnahme"
            model = whisper_model or _pick_default_whisper_model()

            mid = meeting_store.create_meeting(
                title=display_title,
                language=language,
                whisper_model=model,
                diar_model="pyannote/speaker-diarization-3.1",
                status="recording",
            )

            try:
                self._recorder = AudioRecorder(max_buffer_sec=MAX_RECORDING_SEC)
                self._recorder.start()
            except Exception:
                meeting_store.delete_meeting(mid)
                raise

            self._meeting_id = mid
            self._title = display_title
            self._language = language
            self._whisper_model = model

        _log.info("recording started: meeting=%s title=%r", mid, display_title)
        emit_event(
            "recording.started",
            {"meeting_id": mid, "title": display_title},
        )
        return {"ok": True, "meeting_id": mid, "title": display_title}

    def stop(self) -> dict:
        with self._lock:
            if not self.is_recording or self._recorder is None or self._meeting_id is None:
                raise RuntimeError("Keine laufende Aufnahme.")

            audio = self._recorder.stop()
            mid = self._meeting_id
            language = self._language
            model = self._whisper_model or "medium"

            # Reset state immediately so a follow-up start() works.
            self._recorder = None
            self._meeting_id = None
            self._title = None

        sample_rate = AudioRecorder.SAMPLE_RATE
        duration_ms = int(len(audio) * 1000 / sample_rate) if audio.size else 0

        # Diagnostic logging — peak helps us see whether the mic is
        # actually picking up speech-level audio. We DON'T normalize:
        # peak-boost amplifies background noise just as much as speech, so
        # on a quiet laptop mic in a noisy room it makes Whisper hallucinate.
        # Writing FLOAT WAV preserves the original dynamic range, no
        # quantization loss across the encode/decode round trip.
        try:
            import numpy as np

            if audio.size:
                peak = float(np.abs(audio).max())
                rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
                _log.info(
                    "recording[%s] %d samples (%.2fs), peak=%.4f, rms=%.4f",
                    mid[:8],
                    audio.size,
                    duration_ms / 1000.0,
                    peak,
                    rms,
                )
        except Exception:
            _log.exception("audio diagnostic logging failed")

        # File IO outside the lock.
        folder = meeting_store.meeting_folder(mid)
        wav_path = folder / "source.wav"
        try:
            import soundfile as sf

            sf.write(str(wav_path), audio, sample_rate, subtype="FLOAT")
        except Exception as e:
            _log.exception("failed to save recording wav for %s", mid)
            meeting_store.set_status(mid, "error")
            emit_event(
                "meeting.error",
                {"meeting_id": mid, "stage": "decode", "message": f"WAV-Export fehlgeschlagen: {e}"},
            )
            raise

        meeting_store.set_audio_path(mid, str(wav_path))
        meeting_store.set_duration(mid, duration_ms)
        meeting_store.set_status(mid, "processing")

        emit_event(
            "recording.stopped",
            {"meeting_id": mid, "duration_ms": duration_ms},
        )

        # Hand off to the offline pipeline. Same worker pattern as
        # meeting.import_file: returns immediately, drives progress events.
        def _worker() -> None:
            _log.info("rec-pipeline[%s] started", mid[:8])
            try:
                run_stages(
                    mid,
                    str(wav_path),
                    language=language,
                    whisper_model=model,
                    on_event=emit_event,
                )
                _log.info("rec-pipeline[%s] done", mid[:8])
            except Exception:
                _log.exception("rec-pipeline[%s] failed", mid[:8])

        threading.Thread(
            target=_worker,
            name=f"rec-pipeline-{mid[:8]}",
            daemon=True,
        ).start()

        return {"ok": True, "meeting_id": mid, "duration_ms": duration_ms}

    def pause(self) -> dict:
        with self._lock:
            if not self.is_recording or self._recorder is None:
                raise RuntimeError("Keine laufende Aufnahme.")
            self._recorder.pause()
            mid = self._meeting_id
        emit_event("recording.paused", {"meeting_id": mid})
        _log.info("recording paused: meeting=%s", mid)
        return {"ok": True, "meeting_id": mid}

    def resume(self) -> dict:
        with self._lock:
            if not self.is_recording or self._recorder is None:
                raise RuntimeError("Keine laufende Aufnahme.")
            self._recorder.resume()
            mid = self._meeting_id
        emit_event("recording.resumed", {"meeting_id": mid})
        _log.info("recording resumed: meeting=%s", mid)
        return {"ok": True, "meeting_id": mid}

    def cancel(self) -> dict:
        """Stop the mic and discard everything (meeting row + audio)."""
        with self._lock:
            if not self.is_recording or self._recorder is None or self._meeting_id is None:
                return {"ok": False, "reason": "not recording"}
            try:
                self._recorder.stop()
            except Exception:
                pass
            mid = self._meeting_id
            self._recorder = None
            self._meeting_id = None
            self._title = None

        meeting_store.delete_meeting(mid)
        emit_event("recording.cancelled", {"meeting_id": mid})
        _log.info("recording cancelled: meeting=%s", mid)
        return {"ok": True, "meeting_id": mid}

    def state(self) -> dict:
        """Current session state — useful for the UI to recover after a
        page reload (HMR or a window re-open)."""
        return {
            "is_recording": self.is_recording,
            "is_paused": self.is_paused,
            "meeting_id": self._meeting_id,
            "title": self._title,
            "language": self._language,
            "whisper_model": self._whisper_model,
        }
