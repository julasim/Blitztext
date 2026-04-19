"""Global hotkey listener — hold-to-record semantics with reliable suppression.

On Windows, `keyboard.add_hotkey(..., suppress=True)` uses an internal
timeout-based suppressor that in some combinations still lets the trigger
key leak through to the focused window (a digit gets typed into whatever
has focus). To avoid that we register a single low-level
`keyboard.hook(…, suppress=True)` and do our own modifier tracking, so
the callback can return ``False`` directly and block the event at the
driver level.
"""

import threading
from typing import Callable
import keyboard

from core.log import log


# Aliases `keyboard` emits on Windows that we normalise to a canonical name.
# Keep in sync with the regex in _split_hotkey() below.
_NORMALIZE = {
    # German modifier names, depending on keyboard layout
    "strg": "ctrl", "steuerung": "ctrl",
    # Qualified left/right variants for all modifiers
    "left ctrl": "ctrl", "right ctrl": "ctrl",
    "left shift": "shift", "right shift": "shift",
    "umschalt": "shift", "umsch": "shift",
    "left alt": "alt", "right alt": "alt",
    "alt gr": "alt", "altgr": "alt",
    "left windows": "win", "right windows": "win", "windows": "win", "meta": "win",
}


def _norm(name: str) -> str:
    return _NORMALIZE.get(name.lower(), name.lower())


def _split_hotkey(spec: str) -> tuple[set[str], str]:
    """Split ``"ctrl+alt+1"`` into ({"ctrl","alt"}, "1") — all lowercase."""
    parts = [_norm(p.strip()) for p in spec.split("+") if p.strip()]
    if not parts:
        return set(), ""
    return set(parts[:-1]), parts[-1]


class HotkeyListener:
    """Listens for global hotkeys. Each mode has its own hotkey.

    Hold-to-record: the trigger key's press-edge starts a recording,
    the release-edge of the trigger key OR any modifier stops it.
    """

    def __init__(
        self,
        on_start: Callable[[int], None],
        on_stop: Callable[[int], None],
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        # mode → (mods_set, trigger_key)
        self._hotkeys: dict[int, tuple[set[str], str]] = {}
        self._hook = None
        self._active_mode: int | None = None
        self._pressed: set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    # --- Public API ------------------------------------------------------

    def register(self, hotkey_str: str, mode: int) -> None:
        """Register a hotkey for a mode. Overwrites any previous one for that mode."""
        mods, trigger = _split_hotkey(hotkey_str)
        if not trigger:
            log(f"register: invalid hotkey {hotkey_str!r}")
            return
        with self._lock:
            self._hotkeys[mode] = (mods, trigger)

    def start(self) -> None:
        """Install the low-level hook. Blocks until stop() is called."""
        self._remove_hook()

        # suppress=True lets us return False from the callback to drop the
        # event before it reaches the focused window.
        try:
            self._hook = keyboard.hook(self._on_event, suppress=True)
            active = ", ".join(
                f"mode{m}={'+'.join(sorted(mods)|{trig})}"
                for m, (mods, trig) in self._hotkeys.items()
            )
            log(f"keyboard hook installed — {active}")
        except Exception as e:
            log(f"keyboard.hook FAILED: {type(e).__name__}: {e}")
            return

        self._stop_event.clear()
        self._stop_event.wait()

    def stop(self) -> None:
        self._stop_event.set()
        self._remove_hook()
        with self._lock:
            self._active_mode = None
            self._pressed.clear()

    def _reset_active_mode(self) -> None:
        """Clear the active-mode flag. Used when the press callback aborted
        early (e.g. model not loaded) so subsequent presses aren't blocked."""
        with self._lock:
            self._active_mode = None

    # --- Internals -------------------------------------------------------

    def _remove_hook(self) -> None:
        if self._hook is not None:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
            self._hook = None

    def _on_event(self, event) -> bool:
        """Low-level hook callback. Return False to suppress the event.

        Runs on the `keyboard` library's internal thread — must never raise.
        """
        try:
            return self._on_event_impl(event)
        except Exception as e:
            # Log, but always let the event through if we crash — never block
            # the user's keyboard because of our bug.
            try:
                log(f"hook crashed: {type(e).__name__}: {e}")
            except Exception:
                pass
            return True

    def _on_event_impl(self, event) -> bool:
        name = getattr(event, "name", None)
        if not isinstance(name, str) or not name:
            return True
        key = _norm(name)
        etype = getattr(event, "event_type", None)

        if etype == "down":
            self._pressed.add(key)

            # Is this the trigger key for any hotkey whose modifiers are ALL held?
            with self._lock:
                match_mode = None
                for mode, (mods, trigger) in self._hotkeys.items():
                    if key == trigger and mods.issubset(self._pressed):
                        match_mode = mode
                        break

                if match_mode is None:
                    return True  # unrelated key, let it through

                # If we're already recording, swallow this press so it can't
                # leak into the focused window, but don't re-trigger start.
                if self._active_mode is not None:
                    return False

                self._active_mode = match_mode

            # Fire on_start OUTSIDE the lock and off the hook thread so we
            # don't block the keyboard driver while Qt signals propagate.
            threading.Thread(
                target=self._safe_call, args=(self._on_start, match_mode), daemon=True
            ).start()
            return False  # SUPPRESS — trigger key must not reach apps

        if etype == "up":
            self._pressed.discard(key)

            fire_stop = False
            mode = None
            with self._lock:
                if self._active_mode is None:
                    return True
                mods, trigger = self._hotkeys.get(self._active_mode, (set(), ""))
                # Release of the trigger key or any of the required modifiers
                # ends the recording.
                if key == trigger or key in mods:
                    mode = self._active_mode
                    self._active_mode = None
                    fire_stop = True

            if fire_stop and mode is not None:
                threading.Thread(
                    target=self._safe_call, args=(self._on_stop, mode), daemon=True
                ).start()
                # Let key-ups always pass through (no visible key to suppress;
                # suppressing could interfere with the app receiving the
                # up-edge of a modifier it cares about).
            return True

        return True

    @staticmethod
    def _safe_call(fn: Callable, arg) -> None:
        try:
            fn(arg)
        except Exception as e:
            try:
                log(f"hotkey callback {fn.__name__} raised {type(e).__name__}: {e}")
            except Exception:
                pass
