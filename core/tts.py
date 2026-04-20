"""Text-to-speech playback.

Provider pattern mirrors ``core/llm.py`` so additional engines (Edge TTS,
OpenAI TTS, ElevenLabs, …) can be plugged in later without touching the
call site in main.py.

Default provider: **SAPI** via ``pyttsx3`` — works offline with whatever
voices Windows itself ships, zero install footprint beyond the Python
package (~small kB, wrapper over COM).

Design rules:
- Playback runs on a dedicated worker thread so the Qt GUI stays responsive.
- ``stop()`` interrupts playback mid-sentence (SAPI's ``stop()`` primitive).
- ``on_finished`` is called exactly once per ``speak()`` cycle — either
  when playback ends naturally OR after a manual stop. The host uses it
  to flip the "speaking" state back to idle.
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
# Factory
# ---------------------------------------------------------------------------


def make_provider(provider: str, voice_id: str = "", rate_offset: int = 0,
                  language: str = "de") -> TTSProvider:
    """Return a ready-to-use provider instance. Unknown keys fall back to SAPI."""
    p = (provider or "sapi").lower()
    if p == "sapi":
        return _SapiProvider(voice_id=voice_id, rate_offset=rate_offset, language=language)
    log(f"tts: unknown provider {provider!r}, falling back to SAPI")
    return _SapiProvider(voice_id=voice_id, rate_offset=rate_offset, language=language)


def list_voices(provider: str = "sapi") -> list[dict]:
    """Top-level helper used by the settings window when it builds the voice dropdown."""
    return make_provider(provider).voices()
