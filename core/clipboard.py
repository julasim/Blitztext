"""Selection capture via the classic "simulate Ctrl+C, read clipboard,
restore previous clipboard" trick.

Used by the TTS mode to grab the currently-selected text from whatever
app has focus without needing a custom integration per app. Falls back
to the clipboard's current content if no selection is captured within
a short window — that way a plain "copy, press hotkey, listen" flow
also works.

The original clipboard text is always restored in a ``finally`` block,
even if any intermediate step raises. Images, files, and other non-text
clipboard payloads are not preserved by this implementation (pyperclip
is text-only); in practice this is rare enough that the trade-off is
worth it.
"""

import time

import keyboard
import pyperclip

from core.log import log


_SENTINEL = "\x00\x00\x00blitztext-probe\x00\x00\x00"


def _safe_paste() -> str:
    try:
        return pyperclip.paste() or ""
    except Exception as e:
        log(f"clipboard paste failed: {type(e).__name__}: {e}")
        return ""


def _safe_copy(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except Exception as e:
        log(f"clipboard copy failed: {type(e).__name__}: {e}")
        return False


def get_selected_or_clipboard_text(timeout_ms: int = 180) -> str:
    """Return the text the user most likely wants read aloud.

    Strategy:
      1. Snapshot the current clipboard contents (``original``).
      2. If possible, write a unique sentinel so we can detect whether
         the Ctrl+C actually put something new there. If setting the
         sentinel fails, fall back to comparing against ``original``.
      3. Simulate Ctrl+C.
      4. Poll briefly for the clipboard to change.
      5. Restore ``original`` in a ``finally`` block — this runs even
         if anything above raises, so the sentinel can never leak out
         to the user's real clipboard.

    Returns an empty string if neither a selection nor a non-empty
    pre-existing clipboard content can be found.
    """
    original = _safe_paste()
    sentinel_set = _safe_copy(_SENTINEL)

    try:
        try:
            keyboard.send("ctrl+c")
        except Exception as e:
            log(f"keyboard.send ctrl+c failed: {type(e).__name__}: {e}")

        deadline = time.time() + (timeout_ms / 1000.0)
        selected = ""
        while time.time() < deadline:
            cur = _safe_paste()
            if sentinel_set:
                # A change away from our sentinel means Ctrl+C landed.
                if cur and cur != _SENTINEL:
                    selected = cur
                    break
            else:
                # Without a sentinel, fall back to detecting any change from
                # the pre-existing clipboard content.
                if cur and cur != original:
                    selected = cur
                    break
            time.sleep(0.015)

        return selected or original
    finally:
        # Always restore whatever the user had in the clipboard before we
        # poked it. Run under a nested try so a failing restore can't mask
        # any exception raised inside the try-block.
        try:
            if original:
                _safe_copy(original)
            else:
                # Defensive: if no original was captured and the sentinel is
                # still sitting there, replace it with an empty string so the
                # user doesn't see our debug marker in their clipboard.
                cur = _safe_paste()
                if cur == _SENTINEL:
                    _safe_copy("")
        except Exception:
            pass
