import numpy as np
import sounddevice as sd
import threading


class AudioRecorder:
    """Records audio from the default microphone into a buffer."""

    SAMPLE_RATE = 16000  # Whisper expects 16kHz
    CHANNELS = 1
    DTYPE = "float32"

    def __init__(self):
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._buffer.clear()
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
            return audio

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        # Lock protects concurrent access to _buffer from stop()
        with self._lock:
            if self._recording:
                self._buffer.append(indata.copy())
