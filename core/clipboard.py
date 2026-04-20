"""Selection capture via the classic "simulate Ctrl+C, read clipboard,
restore previous clipboard" trick.

Used by the TTS mode to grab the currently-selected text from whatever
app has focus without needing a custom integration per app. Falls back
to the clipboard's current content if no selection is captured within
a short window — that way a plain "copy, press hotkey, listen" flow
also works.

The original clipboard text is restored afterwards so the user's
copy-paste state isn't trampled by our transient Ctrl+C simulation.
Images, files, and other non-text clipboard payloads are not preserved
by this implementation (pyperclip is text-only); in practice this is
rare enough that the trade-off is worth it.
"""

import time

import keyboard
import pyperclip

from core.log import log


def get_selected_or_clipboard_text(timeout_ms: int = 180) -> str:
    """Return the text the user most likely wants read aloud.

    Strategy:
      1. Snapshot the current clipboard contents.
      2. Simulate Ctrl+C to copy the current selection.
      3. Poll briefly for the clipboard to change.
      4. If it did, return the new text (= the selection).
      5. If not, return the already-snapshotted text (= whatever was
         already in the clipboard when the hotkey was pressed).
      6. Restore the snapshotted text to the clipboard so the user's
         copy-paste state isn't disturbed.

    Returns an empty string if both selection and clipboard are empty.
    """
    try:
        original = pyperclip.paste() or ""
    except Exception as e:
        log(f"clipboard read (original) failed: {type(e).__name__}: {e}")
        original = ""

    # Nudge the clipboard so we can detect "did Ctrl+C change it?" even
    # when the selection is identical to `original`.
    _SENTINEL = "\x00\x00\x00blitztext-probe\x00\x00\x00"
    try:
        pyperclip.copy(_SENTINEL)
    except Exception:
        pass

    try:
        keyboard.send("ctrl+c")
    except Exception as e:
        log(f"keyboard.send ctrl+c failed: {type(e).__name__}: {e}")

    # Poll for the clipboard to become something other than the sentinel.
    deadline = time.time() + (timeout_ms / 1000.0)
    selected = ""
    while time.time() < deadline:
        try:
            cur = pyperclip.paste() or ""
        except Exception:
            cur = ""
        if cur and cur != _SENTINEL:
            selected = cur
            break
        time.sleep(0.015)

    # Restore whatever the user had in the clipboard before we poked it.
    try:
        if original:
            pyperclip.copy(original)
        else:
            # Couldn't read it or it was empty — at least don't leave the sentinel behind.
            if pyperclip.paste() == _SENTINEL:
                pyperclip.copy("")
    except Exception:
        pass

    # If Ctrl+C didn't yield a selection, fall back to the user's pre-existing clipboard.
    return selected or original
