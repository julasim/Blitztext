"""Text-to-speech playback.

Two backends implement the same ``TTSProvider`` interface:

- **SAPI** (default, always available) — Windows-built-in voices via
  ``pyttsx3``. Robust and instant, but the voices are fairly robotic.
- **Piper** (optional, recommended) — neural voices via ``piper-tts`` +
  ``onnxruntime``. Much more natural German output. Runs fully offline
  once a voice model (~15–65 MB ``.onnx``) has been downloaded to
  ``%APPDATA%\\Blitztext\\voices\\`` by ``core.voice_download``.

Design rules:
- Playback always runs on a dedicated worker thread so the Qt GUI stays
  responsive.
- ``stop()`` interrupts playback mid-sentence.
- ``on_finished`` is called exactly once per ``speak()`` cycle — either
  when playback ends naturally OR after a manual stop. The host uses it
  to flip the "speaking" state back to idle.
- Factory ``make_provider()`` falls back to SAPI if the requested
  backend can't be constructed or its voice isn't installed yet, so a
  misconfigured setup never leaves the user with silent TTS.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from core.log import log


class TTSProvider:
    """Interface every TTS backend implements."""

    def speak(self, text: str, on_finished: Callable[[], None]) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def voices(self) -> list[dict]:
        """Return a list of ``{id, name, language}`` describing available voices.
        Empty list is acceptable — the settings UI then just shows a placeholder."""
        return []


# ---------------------------------------------------------------------------
# SAPI via pyttsx3
# ---------------------------------------------------------------------------


class _SapiProvider(TTSProvider):
    """Windows SAPI backend.

    pyttsx3 is strictly single-threaded and has a global engine lifecycle.
    We keep one engine per provider instance and run ``runAndWait`` on a
    worker thread. ``stop()`` aborts playback cleanly.
    """

    def __init__(self, voice_id: str = "", rate_offset: int = 0, language: str = "de"):
        self._voice_id = voice_id
        self._rate_offset = rate_offset      # -10 .. +10, maps to ±80 wpm around default
        self._language = language
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._engine = None

    # -- helpers -----------------------------------------------------------

    def _build_engine(self):
        import pyttsx3
        engine = pyttsx3.init()
        # Rate: SAPI default is ~200 wpm; map -10..+10 to ~-80..+80 wpm.
        try:
            default = int(engine.getProperty("rate") or 200)
            engine.setProperty("rate", max(80, default + 8 * self._rate_offset))
        except Exception as e:
            log(f"tts: could not set rate: {e}")

        # Voice: either the one the user picked, or the first one matching our language.
        try:
            voices = engine.getProperty("voices") or []
            chosen = None
            if self._voice_id:
                for v in voices:
                    if v.id == self._voice_id:
                        chosen = v.id
                        break
            if not chosen:
                lang_tag = (self._language or "de").lower()
                for v in voices:
                    langs = [str(l).lower() for l in getattr(v, "languages", [])]
                    name = (getattr(v, "name", "") or "").lower()
                    if lang_tag in name or any(lang_tag in l for l in langs):
                        chosen = v.id
                        break
            if chosen:
                engine.setProperty("voice", chosen)
        except Exception as e:
            log(f"tts: could not set voice: {e}")

        return engine

    # -- public API --------------------------------------------------------

    def speak(self, text: str, on_finished: Callable[[], None]) -> None:
        text = (text or "").strip()
        if not text:
            log("tts: empty text, skipping")
            on_finished()
            return

        # Any previous playback has to be torn down first.
        self.stop()

        def _run():
            try:
                engine = self._build_engine()
                with self._lock:
                    self._engine = engine
                log(f"tts: speaking {len(text)} chars")
                engine.say(text)
                engine.runAndWait()
                try:
                    engine.stop()
                except Exception:
                    pass
            except Exception as e:
                log(f"tts: SAPI crashed: {type(e).__name__}: {e}")
            finally:
                with self._lock:
                    self._engine = None
                try:
                    on_finished()
                except Exception as e:
                    log(f"tts: on_finished raised: {type(e).__name__}: {e}")

        self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        with self._lock:
            eng = self._engine
        if eng is not None:
            try:
                eng.stop()
            except Exception as e:
                log(f"tts: stop() failed: {type(e).__name__}: {e}")

    def voices(self) -> list[dict]:
        """List available SAPI voices. Called from the settings UI on demand."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            out = []
            for v in engine.getProperty("voices") or []:
                langs = [str(l) for l in getattr(v, "languages", [])]
                out.append({
                    "id": v.id,
                    "name": getattr(v, "name", v.id),
                    "language": ", ".join(langs) if langs else "",
                })
            try:
                engine.stop()
            except Exception:
                pass
            return out
        except Exception as e:
            log(f"tts: could not enumerate voices: {type(e).__name__}: {e}")
            return []


# ---------------------------------------------------------------------------
# Piper (neural, offline)
# ---------------------------------------------------------------------------


class _PiperProvider(TTSProvider):
    """Neural TTS via piper-tts + onnxruntime.

    Loads a ``.onnx`` voice model on first ``speak()`` (lazy — startup of
    the main app stays snappy). Synthesis yields one ``AudioChunk`` per
    sentence, each chunk is played synchronously on the worker thread
    via ``sounddevice``. A ``threading.Event`` is polled between chunks
    (and also triggers ``sd.stop()`` during ``stop()``) so the user's
    Esc / second-hotkey-press interrupts playback within one sentence.
    """

    def __init__(self, voice_id: str = "", rate_offset: int = 0, language: str = "de"):
        self._voice_id = voice_id or ""
        self._rate_offset = rate_offset
        self._language = language
        self._lock = threading.Lock()
        self._voice = None  # cached PiperVoice, built lazily
        self._cancel = threading.Event()
        self._worker: Optional[threading.Thread] = None

    # -- helpers -----------------------------------------------------------

    def _model_path(self) -> str:
        # Local import so ``core.tts`` stays importable on machines where
        # voice_download's httpx dep is present but piper-tts isn't.
        from core.voice_download import voice_paths
        onnx, _ = voice_paths(self._voice_id)
        return onnx

    def _synthesis_config(self):
        """Map rate_offset (-6..+6) to piper's length_scale.

        Piper's ``length_scale`` is inversely proportional to speed:
        smaller = faster. 1.0 is neutral, 0.85 is a noticeable speedup,
        1.15 slows things down. We map the user's -6..+6 slider onto
        roughly 1.30 .. 0.70.
        """
        from piper import SynthesisConfig
        # length_scale: 1.0 - offset * 0.05   → +6 = 0.70 (fast), -6 = 1.30 (slow)
        scale = max(0.55, min(1.50, 1.0 - 0.05 * (self._rate_offset or 0)))
        return SynthesisConfig(length_scale=scale)

    def _ensure_voice(self):
        if self._voice is not None:
            return
        from piper import PiperVoice
        path = self._model_path()
        log(f"tts(piper): loading voice from {path}")
        self._voice = PiperVoice.load(path)
        log(f"tts(piper): voice loaded, sample_rate={self._voice.config.sample_rate}")

    # -- public API --------------------------------------------------------

    def speak(self, text: str, on_finished: Callable[[], None]) -> None:
        text = (text or "").strip()
        if not text:
            log("tts(piper): empty text, skipping")
            on_finished()
            return

        # Any previous playback has to be torn down first.
        self.stop()
        self._cancel.clear()

        def _run():
            try:
                import sounddevice as sd
                self._ensure_voice()
                syn_config = self._synthesis_config()
                log(f"tts(piper): speaking {len(text)} chars, voice={self._voice_id}")
                for chunk in self._voice.synthesize(text, syn_config=syn_config):
                    if self._cancel.is_set():
                        break
                    try:
                        sd.play(chunk.audio_int16_array, chunk.sample_rate, blocking=True)
                    except Exception as e:
                        log(f"tts(piper): sd.play failed: {type(e).__name__}: {e}")
                        break
                    if self._cancel.is_set():
                        break
            except Exception as e:
                log(f"tts(piper): synthesis crashed: {type(e).__name__}: {e}")
            finally:
                try:
                    on_finished()
                except Exception as e:
                    log(f"tts(piper): on_finished raised: {type(e).__name__}: {e}")

        self._worker = threading.Thread(target=_run, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        """Interrupt any in-flight playback."""
        self._cancel.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception as e:
            log(f"tts(piper): sd.stop failed: {type(e).__name__}: {e}")

    def voices(self) -> list[dict]:
        """Return the catalogued Piper voices plus an ``installed`` flag so
        the settings UI can distinguish cached from uncached voices."""
        from config.defaults import PIPER_VOICES
        from core.voice_download import is_voice_installed
        out = []
        for vid, meta in PIPER_VOICES.items():
            out.append({
                "id":        vid,
                "name":      meta.get("label", vid),
                "language":  "de-DE",
                "size_mb":   meta.get("size_mb", 0),
                "installed": is_voice_installed(vid),
            })
        return out


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_provider(provider: str, voice_id: str = "", rate_offset: int = 0,
                  language: str = "de") -> TTSProvider:
    """Return a ready-to-use provider instance.

    Falls back to SAPI (always available on Windows) when:
    - the ``provider`` key is unknown
    - the piper-tts package can't be imported
    - the requested piper voice isn't installed yet
    - constructing the provider raised for any other reason

    The fallback is logged so the user has an audit trail.
    """
    p = (provider or "sapi").lower()

    if p == "piper":
        try:
            # Validate the Piper stack is importable without actually loading
            # the voice (which only happens on first speak()).
            import piper  # noqa: F401
            import sounddevice  # noqa: F401
            from core.voice_download import is_voice_installed
            if voice_id and not is_voice_installed(voice_id):
                log(
                    f"tts: piper voice {voice_id!r} not installed, "
                    f"falling back to SAPI"
                )
                return _SapiProvider(voice_id="", rate_offset=rate_offset, language=language)
            return _PiperProvider(voice_id=voice_id, rate_offset=rate_offset, language=language)
        except ImportError as e:
            log(f"tts: piper not available ({e}), falling back to SAPI")
            return _SapiProvider(voice_id="", rate_offset=rate_offset, language=language)
        except Exception as e:
            log(f"tts: piper init raised {type(e).__name__}: {e}, falling back to SAPI")
            return _SapiProvider(voice_id="", rate_offset=rate_offset, language=language)

    if p == "sapi":
        return _SapiProvider(voice_id=voice_id, rate_offset=rate_offset, language=language)

    log(f"tts: unknown provider {provider!r}, falling back to SAPI")
    return _SapiProvider(voice_id=voice_id, rate_offset=rate_offset, language=language)


def list_voices(provider: str = "sapi") -> list[dict]:
    """Top-level helper used by the settings window when it builds the voice dropdown."""
    p = (provider or "sapi").lower()
    if p == "piper":
        # Don't construct a real provider (would try to import onnxruntime);
        # voice metadata comes straight from the catalogue + cache check.
        try:
            return _PiperProvider().voices()
        except Exception as e:
            log(f"tts: list_voices(piper) failed: {type(e).__name__}: {e}")
            return []
    return make_provider(p).voices()
