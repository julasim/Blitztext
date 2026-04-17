import threading
import time

import pyperclip
import pyautogui


# Disable pyautogui fail-safe (mouse to corner) since we run in the background
pyautogui.FAILSAFE = False


def _restore_clipboard_delayed(previous: str) -> None:
    """Restore clipboard content after a safe delay (runs in background thread)."""
    time.sleep(0.5)
    try:
        pyperclip.copy(previous)
    except Exception:
        pass


def inject_text(text: str) -> None:
    """Copy text to clipboard and simulate Ctrl+V at the current cursor position.

    The previous clipboard content is restored asynchronously after a safe delay
    (500 ms), so the paste has definitively completed before we overwrite.
    """
    if not text:
        return

    try:
        previous = pyperclip.paste()
    except Exception:
        previous = ""

    pyperclip.copy(text)
    time.sleep(0.03)
    pyautogui.hotkey("ctrl", "v")

    # Restore previous clipboard in the background so we don't block here
    threading.Thread(
        target=_restore_clipboard_delayed, args=(previous,), daemon=True
    ).start()
