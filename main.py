"""VoiceType – Speech-to-text with one hotkey."""

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

import atexit
import threading

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt

from config import settings
from core.log import log, log_exc, reset as reset_log
from core.audio import AudioRecorder
from core.transcription import Transcriber
from core.injector import inject_text
from core.hotkey import HotkeyListener
from core.llm import process_text
from core.updater import check_for_update, CURRENT_VERSION
from core.update_installer import download_installer, launch_installer_and_quit
from ui.tray import SystemTray
from ui.settings_window import SettingsWindow
from ui.download_dialog import DownloadDialog
from ui.recording_overlay import RecordingOverlay
from ui.update_dialog import UpdateDialog


class VoiceTypeApp:
    def __init__(self):
        reset_log()
        log(f"App init — frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("VoiceType")

        self._cfg = settings.load()
        # API key of the currently selected provider (cached for fast access from hotkey thread)
        self._api_key = settings.get_provider_key(self._cfg.get("llm_provider", "openrouter"))

        # Prefer the "small" model for speed. Auto-migrate older defaults that
        # were too slow on CPU (base is too inaccurate, large-v3-turbo too slow).
        FAST_DEFAULT = "small"
        if self._cfg.get("whisper_model") in ("base", "large-v3-turbo"):
            self._cfg["whisper_model"] = FAST_DEFAULT
            settings.save(self._cfg)

        self._recorder = AudioRecorder()
        self._transcriber = Transcriber(
            model_size=self._cfg["whisper_model"],
            language=self._cfg.get("language", "de"),
        )

        self._tray = SystemTray(self._app)
        self._tray.signals.open_settings.connect(self._open_settings)
        self._tray.signals.quit_app.connect(self._quit)

        self._settings_window: SettingsWindow | None = None
        self._download_dialog: DownloadDialog | None = None
        self._recording_overlay = RecordingOverlay()

        self._processing = False
        self._processing_lock = threading.Lock()

        self._hotkey_listener = HotkeyListener(
            on_start=self._on_recording_start,
            on_stop=self._on_recording_stop,
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
            self._invoke_main(lambda: dialog.report(done, total, status))

        def do_load():
            try:
                log("Model load thread started")
                self._transcriber.load(on_progress=on_progress)
                log("Model load complete")
                self._invoke_main(self._on_model_loaded)
            except Exception as e:
                log(f"Model load FAILED: {type(e).__name__}: {e}")
                self._invoke_main(lambda: self._on_model_error(str(e)))

        self._tray.set_state("processing")
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
        self._tray.set_state("idle")
        self._tray.show_message("VoiceType", "Bereit! Whisper-Modell geladen.")

    def _on_model_error(self, error: str) -> None:
        self._close_download_dialog()
        self._tray.set_state("idle")
        self._tray.show_message("VoiceType – Fehler", f"Whisper-Modell konnte nicht geladen werden:\n{error}")

    def _register_hotkeys(self) -> None:
        h1 = self._cfg.get("hotkey_mode1", "ctrl+alt+1")
        h2 = self._cfg.get("hotkey_mode2", "ctrl+alt+2")
        h3 = self._cfg.get("hotkey_mode3", "ctrl+alt+3")
        log(f"Register hotkeys: mode1={h1} mode2={h2} mode3={h3}")
        self._hotkey_listener.register(h1, 1)
        self._hotkey_listener.register(h2, 2)
        self._hotkey_listener.register(h3, 3)

    def _on_recording_start(self, mode: int) -> None:
        log(f"Hotkey pressed — mode={mode} model_loaded={self._transcriber.is_loaded} processing={self._processing}")
        if not self._transcriber.is_loaded:
            log("  → ignoring, model not loaded yet")
            # Let the listener know we're NOT actually recording, so the
            # release doesn't look for a recorder that was never started.
            self._hotkey_listener._reset_active_mode()
            self._invoke_main(lambda: self._tray.show_message(
                "VoiceType", "Sprachmodell wird noch geladen. Bitte warten bis der Download fertig ist.",
            ))
            return
        with self._processing_lock:
            if self._processing:
                return
        try:
            self._recorder.start()
        except Exception as e:
            self._invoke_main(lambda: self._tray.show_message(
                "VoiceType – Fehler", str(e),
            ))
            return
        self._invoke_main(lambda: self._tray.set_state("recording"))
        self._invoke_main(self._recording_overlay.show_overlay)

    def _on_recording_stop(self, mode: int) -> None:
        log(f"Hotkey released — mode={mode}")
        self._invoke_main(self._recording_overlay.hide_overlay)
        audio = self._recorder.stop()
        import numpy as _np
        peak = float(_np.abs(audio).max()) if audio.size > 0 else 0.0
        rms = float(_np.sqrt(_np.mean(audio ** 2))) if audio.size > 0 else 0.0
        log(f"Audio captured: {audio.size} samples ({audio.size/16000:.1f}s)  peak={peak:.3f}  rms={rms:.3f}")
        if audio.size == 0:
            self._invoke_main(lambda: self._tray.set_state("idle"))
            self._invoke_main(lambda: self._tray.show_message(
                "VoiceType", "Aufnahme war zu kurz oder leer.",
            ))
            return
        threading.Thread(target=self._process_audio, args=(audio, mode), daemon=True).start()

    def _process_audio(self, audio, mode: int) -> None:
        with self._processing_lock:
            self._processing = True
        self._invoke_main(lambda: self._tray.set_state("processing"))
        try:
            log(f"Transcribing {audio.size} samples …")
            text = self._transcriber.transcribe(audio)
            log(f"Transcribed: {text!r}")
            if not text:
                self._invoke_main(lambda: self._tray.show_message(
                    "VoiceType", "Keine Sprache erkannt.",
                ))
                return

            if mode in (2, 3):
                provider = self._cfg.get("llm_provider", "openrouter")
                log(f"LLM mode {mode} via {provider} (key set: {bool(self._api_key)})")
                if not self._api_key:
                    self._invoke_main(lambda: self._tray.show_message(
                        "VoiceType", "Kein API-Key gesetzt. Bitte in Einstellungen eintragen."
                    ))
                    return
                text = process_text(
                    text, mode, provider, self._api_key,
                    self._cfg.get("llm_model", ""),
                )
                log(f"LLM returned: {text[:80]!r}")

            log("Injecting text …")
            inject_text(text)
            log("Injection done")
        except Exception as e:
            log_exc("_process_audio failed")
            err = str(e)
            self._invoke_main(lambda: self._tray.show_message("VoiceType – Fehler", err))
        finally:
            with self._processing_lock:
                self._processing = False
            self._invoke_main(lambda: self._tray.set_state("idle"))

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

    def _invoke_main(self, fn) -> None:
        """Run a callable on the Qt main thread."""
        QTimer.singleShot(0, fn)


def main():
    app = VoiceTypeApp()
    sys.exit(app.run())


if __name__ == "__main__":
    main()
