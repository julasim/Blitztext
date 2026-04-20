"""Blitztext – Speech-to-text with one hotkey."""

import os
import sys

# Disable HuggingFace's xet accelerator BEFORE importing huggingface_hub,
# so downloads go through the standard HTTP path with visible tqdm progress.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_HF_XET", "1")
os.environ.setdefault("HF_XET_ENABLED", "0")

# Ensure local packages (core/, config/, ui/) resolve regardless of how the script is invoked.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# Run one-time rename migrations (AppData folder, keyring service, autostart
# registry value) BEFORE the log module or settings are touched, so the very
# first read/write already lands under the new Blitztext names.
from core.migration import migrate_all as _migrate_all
_migrate_all()

import atexit
import threading

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt, QObject, pyqtSignal

from config import settings
from core.log import log, log_exc, reset as reset_log
from core.audio import AudioRecorder
from core.transcription import Transcriber
from core.injector import inject_text
from core.hotkey import HotkeyListener
from core.llm import process_text
from core.tts import make_provider as make_tts_provider
from core.clipboard import get_selected_or_clipboard_text
from core.updater import check_for_update, CURRENT_VERSION
from core.update_installer import download_installer, launch_installer_and_quit
from ui.tray import SystemTray
from ui.home_window import HomeWindow
from ui.settings_window import SettingsWindow
from ui.download_dialog import DownloadDialog
from ui.recording_overlay import RecordingOverlay
from ui.update_dialog import UpdateDialog


class _MainThreadInvoker(QObject):
    """Run callables on the Qt main thread from any thread.

    QTimer.singleShot from a thread without an event loop fires unreliably.
    A pyqtSignal with a QueuedConnection is the documented thread-safe way.
    """
    _call = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, fn):
        try:
            fn()
        except Exception as e:
            log(f"_invoke_main callback failed: {type(e).__name__}: {e}")

    def invoke(self, fn):
        self._call.emit(fn)


class BlitztextApp:
    def __init__(self):
        reset_log()
        log(f"App init — frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Blitztext")

        # Must be created on the main (GUI) thread — used for all cross-thread UI calls.
        self._invoker = _MainThreadInvoker()

        self._cfg = settings.load()
        # API key of the currently selected provider (cached for fast access from hotkey thread)
        self._api_key = settings.get_provider_key(self._cfg.get("llm_provider", "openrouter"))

        # Default model = medium (balance of German quality and CPU speed).
        # Only migrate configs that still hold one of our previous auto-defaults;
        # if the user picked a model explicitly (outside this list), respect it.
        if self._cfg.get("whisper_model") in ("base", "small", "large-v3-turbo"):
            self._cfg["whisper_model"] = "medium"
            settings.save(self._cfg)

        self._recorder = AudioRecorder()
        self._transcriber = Transcriber(
            model_size=self._cfg["whisper_model"],
            language=self._cfg.get("language", "de"),
        )

        self._tray = SystemTray(self._app)
        self._tray.signals.open_settings.connect(self._open_settings)
        self._tray.signals.quit_app.connect(self._quit)
        self._tray.signals.open_home.connect(self._open_home)

        self._settings_window: SettingsWindow | None = None
        self._download_dialog: DownloadDialog | None = None
        self._recording_overlay = RecordingOverlay()

        # Home popup — shown on tray left-click. One instance, reused across opens.
        self._home_window = HomeWindow(self._cfg)
        self._home_window.open_settings.connect(self._open_settings)
        self._home_window.quit_app.connect(self._quit)

        self._processing = False
        self._processing_lock = threading.Lock()
        # TTS playback is mutually exclusive with dictation — tracked via
        # self._speaking + the hotkey listener's single active mode.
        # The lock is needed because the TTS worker thread flips _speaking
        # back to False in its finally-clause while the hotkey thread may
        # simultaneously read it in _on_recording_start (to stop any
        # active playback before starting a new recording).
        self._speaking = False
        self._speaking_lock = threading.Lock()
        # Auto-stop safety net: when toggle-mode recording has been running
        # for this many seconds, we force-stop it. Prevents a forgotten-about
        # recording from eating unbounded RAM and making Whisper chug for
        # hours. The AudioRecorder has its own deeper cap as a second line.
        self._max_recording_sec = 600  # 10 minutes
        self._max_duration_timer: threading.Timer | None = None
        self._tts = make_tts_provider(
            provider=self._cfg.get("tts_provider", "sapi"),
            voice_id=self._cfg.get("tts_voice", ""),
            rate_offset=int(self._cfg.get("tts_rate", 0) or 0),
            language=self._cfg.get("language", "de"),
        )

        self._hotkey_listener = HotkeyListener(
            on_start=self._on_hotkey_start,
            on_stop=self._on_hotkey_stop,
        )
        self._register_hotkeys()

        # Ensure the Windows autostart entry reflects the current config on every launch.
        # (No-op in dev mode; only writes the registry when running as the installed .exe.)
        settings.set_autostart(self._cfg.get("start_with_windows", True))

        atexit.register(self._cleanup)

    def run(self) -> int:
        self._load_model_async()
        threading.Thread(target=self._check_update, daemon=True).start()
        threading.Thread(target=self._run_listener, daemon=True).start()
        return self._app.exec()

    def _run_listener(self) -> None:
        try:
            self._hotkey_listener.start()
        except Exception as e:
            log(f"Hotkey listener crashed: {type(e).__name__}: {e}")

    def _load_model_async(self) -> None:
        model_name = self._cfg.get("whisper_model", "large-v3-turbo")
        needs_download = not self._transcriber._is_cached()
        log(f"Loading Whisper '{model_name}' — cached={not needs_download}")

        dialog = DownloadDialog(model_name)
        self._download_dialog = dialog
        if needs_download:
            log("Model not cached — showing download dialog immediately")
            dialog.show()
            dialog.raise_()

        def on_progress(done: int, total: int, status: str):
            # dialog.report() emits a pyqtSignal with QueuedConnection, which is
            # already thread-safe and delivers to the GUI thread. No extra
            # QTimer.singleShot wrapping needed (that doesn't fire reliably
            # from a non-Qt thread without an event loop).
            dialog.report(done, total, status)

        def do_load():
            try:
                log("Model load thread started")
                self._transcriber.load(on_progress=on_progress)
                log("Model load complete")
                self._invoke_main(self._on_model_loaded)
            except Exception as e:
                log(f"Model load FAILED: {type(e).__name__}: {e}")
                self._invoke_main(lambda: self._on_model_error(str(e)))

        self._set_state("processing")
        threading.Thread(target=do_load, daemon=True).start()

    def _close_download_dialog(self) -> None:
        if self._download_dialog is not None:
            try:
                self._download_dialog.close()
            except Exception:
                pass
            self._download_dialog = None

    def _on_model_loaded(self) -> None:
        self._close_download_dialog()
        self._set_state("idle")
        self._tray.show_message("Blitztext", "Bereit! Whisper-Modell geladen.")

    def _on_model_error(self, error: str) -> None:
        self._close_download_dialog()
        self._set_state("idle")
        self._tray.show_message("Blitztext – Fehler", f"Whisper-Modell konnte nicht geladen werden:\n{error}")

    def _register_hotkeys(self) -> None:
        self._hotkey_listener.clear()
        h1 = self._cfg.get("hotkey_mode1", "ctrl+alt+1")
        h2 = self._cfg.get("hotkey_mode2", "ctrl+alt+2")
        h3 = self._cfg.get("hotkey_mode3", "ctrl+alt+3")
        h4 = self._cfg.get("hotkey_mode4", "ctrl+alt+4")
        log(f"Register hotkeys: mode1={h1} mode2={h2} mode3={h3} mode4={h4}")
        self._hotkey_listener.register(h1, 1)
        self._hotkey_listener.register(h2, 2)
        self._hotkey_listener.register(h3, 3)
        self._hotkey_listener.register(h4, 4)

    # ---- Hotkey dispatcher (toggle semantics) -----------------------------

    def _on_hotkey_start(self, mode: int) -> None:
        """First press of a hotkey — begin the corresponding action.

        Modes 1-3: start audio recording.
        Mode 4:    snapshot selection and start TTS playback.
        """
        if mode == 4:
            self._start_tts()
        else:
            self._on_recording_start(mode)

    def _on_hotkey_stop(self, mode: int) -> None:
        """Second press of the same hotkey (or Esc) — end the current action."""
        if mode == 4:
            self._stop_tts()
        else:
            self._on_recording_stop(mode)

    # ---- Dictation (modes 1-3) --------------------------------------------

    def _on_recording_start(self, mode: int) -> None:
        log(f"Hotkey pressed — mode={mode} model_loaded={self._transcriber.is_loaded} processing={self._processing}")
        if not self._transcriber.is_loaded:
            log("  → ignoring, model not loaded yet")
            self._hotkey_listener._reset_active_mode()
            self._invoke_main(lambda: self._tray.show_message(
                "Blitztext", "Sprachmodell wird noch geladen. Bitte warten bis der Download fertig ist.",
            ))
            return
        # Warn up-front if LLM modes lack an API key, so user doesn't waste a recording
        if mode in (2, 3) and not self._api_key:
            log(f"  → ignoring, no API key for mode {mode}")
            self._hotkey_listener._reset_active_mode()
            self._invoke_main(lambda: self._tray.show_message(
                "Blitztext", "Kein API-Key gesetzt. Bitte in Einstellungen eintragen.",
            ))
            return
        with self._processing_lock:
            if self._processing:
                self._hotkey_listener._reset_active_mode()
                return
        # Never start recording while TTS is speaking — stop TTS first.
        # Read under the lock so we don't race with the TTS on_done callback.
        with self._speaking_lock:
            still_speaking = self._speaking
        if still_speaking:
            self._stop_tts()
        try:
            self._recorder.start()
        except Exception as e:
            self._invoke_main(lambda: self._tray.show_message(
                "Blitztext – Fehler", str(e),
            ))
            self._hotkey_listener._reset_active_mode()
            return
        self._invoke_main(lambda: self._set_state("recording"))
        self._invoke_main(self._recording_overlay.show_overlay)
        self._arm_max_duration_timer(mode)

    # ---- Max-recording auto-stop -----------------------------------------

    def _arm_max_duration_timer(self, mode: int) -> None:
        """Start the safety timer that force-stops recording after N seconds."""
        self._cancel_max_duration_timer()
        t = threading.Timer(
            self._max_recording_sec,
            self._auto_stop_recording, args=(mode,),
        )
        t.daemon = True
        self._max_duration_timer = t
        t.start()

    def _cancel_max_duration_timer(self) -> None:
        t = self._max_duration_timer
        if t is not None:
            try:
                t.cancel()
            except Exception:
                pass
            self._max_duration_timer = None

    def _auto_stop_recording(self, mode: int) -> None:
        """Timer callback: if still recording this mode, stop it cleanly and notify the user."""
        log(f"Auto-stop timer fired for mode {mode}")
        if not self._recorder.is_recording:
            return
        # Notify the user that we stopped for them — this is the only path
        # where the recording ends without a key press, so it's worth a toast.
        minutes = self._max_recording_sec // 60
        self._invoke_main(lambda: self._tray.show_message(
            "Blitztext",
            f"Aufnahme automatisch beendet — Maximaldauer von {minutes} Minuten erreicht.",
        ))
        # Clear the listener state so the next hotkey press starts a new recording
        # (without it, the next press would be interpreted as the STOP of the
        # still-active toggle, and nothing would happen).
        try:
            self._hotkey_listener._reset_active_mode()
        except Exception:
            pass
        # Reuse the normal stop path so transcription + injection still run.
        self._on_recording_stop(mode)

    def _on_recording_stop(self, mode: int) -> None:
        log(f"Hotkey stop — mode={mode}")
        self._cancel_max_duration_timer()
        self._invoke_main(self._recording_overlay.hide_overlay)
        audio = self._recorder.stop()
        import numpy as _np
        peak = float(_np.abs(audio).max()) if audio.size > 0 else 0.0
        rms = float(_np.sqrt(_np.mean(audio ** 2))) if audio.size > 0 else 0.0
        log(f"Audio captured: {audio.size} samples ({audio.size/16000:.1f}s)  peak={peak:.3f}  rms={rms:.3f}")
        if audio.size == 0:
            self._invoke_main(lambda: self._set_state("idle"))
            self._invoke_main(lambda: self._tray.show_message(
                "Blitztext", "Aufnahme war zu kurz oder leer.",
            ))
            return
        threading.Thread(target=self._process_audio, args=(audio, mode), daemon=True).start()

    def _process_audio(self, audio, mode: int) -> None:
        with self._processing_lock:
            self._processing = True
        self._invoke_main(lambda: self._set_state("processing"))
        try:
            log(f"Transcribing {audio.size} samples …")
            text = self._transcriber.transcribe(audio)
            log(f"Transcribed: {text!r}")
            if not text:
                self._invoke_main(lambda: self._tray.show_message(
                    "Blitztext", "Keine Sprache erkannt.",
                ))
                return

            if mode in (2, 3):
                provider = self._cfg.get("llm_provider", "openrouter")
                log(f"LLM mode {mode} via {provider} (key set: {bool(self._api_key)})")
                if not self._api_key:
                    self._invoke_main(lambda: self._tray.show_message(
                        "Blitztext", "Kein API-Key gesetzt. Bitte in Einstellungen eintragen."
                    ))
                    return
                # Per-mode user-edited system prompt (blank → process_text
                # falls back to the built-in default for that mode).
                prompt_key = "llm_prompt_mode2" if mode == 2 else "llm_prompt_mode3"
                custom_prompt = self._cfg.get(prompt_key, "")
                text = process_text(
                    text, mode, provider, self._api_key,
                    self._cfg.get("llm_model", ""),
                    system_prompt=custom_prompt,
                )
                log(f"LLM returned: {text[:80]!r}")

            # Also copy into the clipboard so the user has a safety net: if
            # focus changed during transcription and the injection lands in
            # the wrong window, they can still Ctrl+V into the intended one.
            try:
                import pyperclip
                pyperclip.copy(text)
                log("Text copied to clipboard (memory fallback)")
            except Exception as e:
                log(f"clipboard copy failed: {type(e).__name__}: {e}")

            log("Injecting text …")
            inject_text(text)
            log("Injection done")
        except Exception as e:
            log_exc("_process_audio failed")
            err = str(e)
            self._invoke_main(lambda: self._tray.show_message("Blitztext – Fehler", err))
        finally:
            with self._processing_lock:
                self._processing = False
            self._invoke_main(lambda: self._set_state("idle"))

    # ---- TTS (mode 4) -----------------------------------------------------

    def _start_tts(self) -> None:
        """Snapshot the currently-selected text (or clipboard) and read it aloud.

        The text is captured exactly once, at hotkey-press time, so the user
        can switch windows, scroll, or click around during playback without
        interrupting what's being spoken.
        """
        log("TTS start")
        with self._speaking_lock:
            if self._speaking:
                # Shouldn't happen under toggle semantics (the hotkey would've
                # fired stop instead), but guard against re-entry anyway.
                already_speaking = True
            else:
                already_speaking = False
        if already_speaking:
            self._stop_tts()
            return

        try:
            text = get_selected_or_clipboard_text()
        except Exception as e:
            log(f"TTS selection capture failed: {type(e).__name__}: {e}")
            text = ""
        text = (text or "").strip()
        if not text:
            log("  → no text to speak")
            self._hotkey_listener._reset_active_mode()
            self._invoke_main(lambda: self._tray.show_message(
                "Blitztext", "Nichts zum Vorlesen — markiere Text oder kopiere ihn in die Zwischenablage."
            ))
            return

        # Rebuild the TTS provider each time so voice/rate edits in settings
        # take effect immediately. Cheap on SAPI.
        self._tts = make_tts_provider(
            provider=self._cfg.get("tts_provider", "sapi"),
            voice_id=self._cfg.get("tts_voice", ""),
            rate_offset=int(self._cfg.get("tts_rate", 0) or 0),
            language=self._cfg.get("language", "de"),
        )

        with self._speaking_lock:
            self._speaking = True
        self._invoke_main(lambda: self._set_state("speaking"))
        log(f"  → speaking {len(text)} chars")

        def on_done():
            with self._speaking_lock:
                self._speaking = False
            # Clear the listener's active-mode flag so the next press starts fresh
            # (normally the stop-toggle does this, but natural end-of-speech doesn't
            # go through the hotkey path).
            try:
                self._hotkey_listener._reset_active_mode()
            except Exception:
                pass
            self._invoke_main(lambda: self._set_state("idle"))
            log("TTS finished")

        self._tts.speak(text, on_finished=on_done)

    def _stop_tts(self) -> None:
        log("TTS stop")
        try:
            self._tts.stop()
        except Exception as e:
            log(f"tts.stop failed: {type(e).__name__}: {e}")
        # The provider's on_finished callback will flip _speaking back to False
        # and set idle state. As a belt-and-suspenders we also do it here in case
        # stop() interrupts before the worker thread runs its finally clause.
        with self._speaking_lock:
            self._speaking = False
        self._invoke_main(lambda: self._set_state("idle"))

    def _open_home(self, anchor) -> None:
        """Tray left-click → position & show the home popup near the tray icon."""
        try:
            self._home_window.set_state(self._home_status())
            self._home_window.show_near(anchor)
        except Exception as e:
            log(f"_open_home failed: {type(e).__name__}: {e}")

    def _home_status(self) -> str:
        """Map internal state to the status shown in the home window."""
        with self._speaking_lock:
            speaking = self._speaking
        if speaking:
            return "speaking"
        if self._processing:
            return "processing"
        if not self._transcriber.is_loaded:
            return "loading"
        return "idle"

    def _set_state(self, state: str) -> None:
        """Update tray icon AND home window status in one shot (main thread)."""
        self._tray.set_state(state)
        try:
            self._home_window.set_state(state)
        except Exception:
            # Home window not ready yet (early startup) — tray is enough.
            pass

    def _open_settings(self) -> None:
        try:
            if self._settings_window is not None and self._settings_window.isVisible():
                self._settings_window.activateWindow()
                return
        except RuntimeError:
            self._settings_window = None
        self._hotkey_listener.stop()
        self._settings_window = SettingsWindow(self._cfg)
        self._settings_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._settings_window.settings_saved.connect(self._apply_settings)
        self._settings_window.destroyed.connect(self._on_settings_closed)
        self._settings_window.show()

    def _apply_settings(self, new_settings: dict) -> None:
        # Persist any edited per-provider keys
        provider_keys = new_settings.pop("provider_keys", {})
        for provider, key in provider_keys.items():
            settings.set_provider_key(provider, key)

        old_model = self._cfg.get("whisper_model")
        self._cfg.update(new_settings)
        settings.save(self._cfg)

        # Refresh the cached key for the currently selected provider
        self._api_key = settings.get_provider_key(self._cfg.get("llm_provider", "openrouter"))

        self._transcriber.set_language(self._cfg.get("language", "de"))
        settings.set_autostart(self._cfg.get("start_with_windows", True))
        self._register_hotkeys()
        # Push new hotkey labels into the home window
        self._home_window.set_config(self._cfg)
        # Rebuild the TTS provider with the new voice / rate / language so
        # the next Strg+Alt+4 press uses the updated settings immediately.
        self._tts = make_tts_provider(
            provider=self._cfg.get("tts_provider", "sapi"),
            voice_id=self._cfg.get("tts_voice", ""),
            rate_offset=int(self._cfg.get("tts_rate", 0) or 0),
            language=self._cfg.get("language", "de"),
        )

        # If the Whisper model changed, reload it (shows download dialog if needed)
        new_model = self._cfg.get("whisper_model")
        if new_model and new_model != old_model:
            self._transcriber.set_model(new_model)
            self._load_model_async()

    def _on_settings_closed(self) -> None:
        self._settings_window = None
        threading.Thread(target=self._run_listener, daemon=True).start()

    def _check_update(self) -> None:
        info = check_for_update()
        if info is not None:
            self._invoke_main(lambda: self._show_update_dialog(info))

    def _show_update_dialog(self, info) -> None:
        dialog = UpdateDialog(info.version, CURRENT_VERSION, info.notes)
        self._update_dialog = dialog

        def start_update():
            threading.Thread(
                target=self._run_update_download,
                args=(info.download_url, dialog),
                daemon=True,
            ).start()

        dialog.update_requested.connect(start_update)
        dialog.show()
        dialog.raise_()

    def _run_update_download(self, url: str, dialog: "UpdateDialog") -> None:
        try:
            path = download_installer(
                url,
                progress_callback=lambda done, total: dialog.report_progress(done, total),
            )
            self._invoke_main(lambda: dialog.set_status("Installer wird gestartet …"))
            # Stop listener cleanly before the installer force-closes us
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            launch_installer_and_quit(path)
        except Exception as e:
            err = str(e)
            self._invoke_main(lambda: dialog.set_status(f"Fehler: {err}"))

    def _quit(self) -> None:
        self._cleanup()
        self._app.quit()

    def _cleanup(self) -> None:
        try:
            self._hotkey_listener.stop()
        except Exception:
            pass
        try:
            self._tts.stop()
        except Exception:
            pass
        self._cancel_max_duration_timer()

    def _invoke_main(self, fn) -> None:
        """Run a callable on the Qt main thread (thread-safe via pyqtSignal)."""
        self._invoker.invoke(fn)


def main():
    app = BlitztextApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
