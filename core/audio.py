import numpy as np
import sounddevice as sd
import threading

from core.log import log


class AudioRecorder:
    """Records audio from the default microphone into a buffer.

    Since the toggle-hotkey switch in v1.0.19 the recording duration is
    user-controlled (no longer tied to physical key-release). To prevent
    a forgotten-about recording from filling memory indefinitely, the
    buffer is hard-capped at ``MAX_BUFFER_SEC`` seconds of audio. Further
    frames arriving past the cap are silently dropped (a single warning
    is logged when the cap first trips).

    The UI layer in ``main.py`` runs its own 10-minute auto-stop timer
    as the primary limit; this cap is defence-in-depth in case that
    timer ever fails to fire.
    """

    SAMPLE_RATE = 16000  # Whisper expects 16kHz
    CHANNELS = 1
    DTYPE = "float32"
    # Primary cap = 10 min; add a small safety margin so the UI-side timer
    # has room to trigger the clean stop first.
    MAX_BUFFER_SEC = 11 * 60
    MAX_BUFFER_SAMPLES = MAX_BUFFER_SEC * SAMPLE_RATE

    def __init__(self):
        self._buffer: list[np.ndarray] = []
        self._buffer_samples: int = 0
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False
        self._cap_warned = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._buffer.clear()
            self._buffer_samples = 0
            self._cap_warned = False
            try:
                self._stream = sd.InputStream(
                    samplerate=self.SAMPLE_RATE,
                    channels=self.CHANNELS,
                    dtype=self.DTYPE,
                    callback=self._audio_callback,
                )
                self._stream.start()
            except Exception as e:
                self._stream = None
                raise RuntimeError(f"Kein Mikrofon verfügbar: {e}")
            self._recording = True

    def stop(self) -> np.ndarray:
        with self._lock:
            if not self._recording:
                return np.array([], dtype=self.DTYPE)
            self._recording = False
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            if not self._buffer:
                return np.array([], dtype=self.DTYPE)
            audio = np.concatenate(self._buffer, axis=0).flatten()
            self._buffer.clear()
            self._buffer_samples = 0
            return audio

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        # Lock protects concurrent access to _buffer from stop()
        with self._lock:
            if not self._recording:
                return
            # Hard-cap: silently drop frames once the buffer reaches the
            # safety limit. Log a single warning so a post-mortem shows it.
            if self._buffer_samples + frames > self.MAX_BUFFER_SAMPLES:
                if not self._cap_warned:
                    log(
                        f"AudioRecorder: buffer reached {self.MAX_BUFFER_SEC}s cap — "
                        f"dropping further frames. UI-side auto-stop should have fired already."
                    )
                    self._cap_warned = True
                return
            self._buffer.append(indata.copy())
            self._buffer_samples += frames
