"""Global hotkey listener — toggle semantics with Esc abort.

Each mode has a dedicated hotkey. A single press starts the mode; a
second press of the same hotkey OR the Escape key ends it. Hold and
auto-repeat of the trigger key are filtered out so holding a shortcut
doesn't start/stop/start/stop in rapid succession.

All driver-level events pass through a single ``keyboard.hook(suppress=True)``
hook so we can return ``False`` on matching trigger keys and prevent
them from leaking into the focused window (the classic "pressing Ctrl+Alt+1
types a 1 into Word" bug).
"""

import threading
from typing import Callable
import keyboard

from core.log import log


_NORMALIZE = {
    # German modifier names depending on keyboard layout
    "strg": "ctrl", "steuerung": "ctrl",
    # Qualified left/right variants for all modifiers
    "left ctrl": "ctrl", "right ctrl": "ctrl",
    "left shift": "shift", "right shift": "shift",
    "umschalt": "shift", "umsch": "shift",
    "left alt": "alt", "right alt": "alt",
    "alt gr": "alt", "altgr": "alt",
    "left windows": "win", "right windows": "win",
    "windows": "win", "meta": "win",
    "escape": "esc",
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
    """Listens for global hotkeys with toggle semantics.

    Call sequence for a single mode cycle:
        user presses hotkey        → on_start(mode)
        user presses hotkey again  → on_stop(mode)
        OR user presses Esc        → on_stop(mode)
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
        # Trigger keys we've already acted on this physical keypress — lets us
        # ignore Windows' auto-repeat "down" events and wait for a real release.
        self._consumed: set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    # --- Public API ------------------------------------------------------

    def register(self, hotkey_str: str, mode: int) -> None:
        """Register a hotkey for a mode. Overwrites any previous entry for that mode."""
        mods, trigger = _split_hotkey(hotkey_str)
        if not trigger:
            log(f"register: invalid hotkey {hotkey_str!r}")
            return
        with self._lock:
            self._hotkeys[mode] = (mods, trigger)

    def clear(self) -> None:
        """Remove every registered hotkey. Used before re-registering after settings changes."""
        with self._lock:
            self._hotkeys.clear()

    def start(self) -> None:
        """Install the low-level hook. Blocks until stop() is called."""
        self._remove_hook()

        try:
            self._hook = keyboard.hook(self._on_event, suppress=True)
            active = ", ".join(
                f"mode{m}={'+'.join(sorted(mods)|{trig})}"
                for m, (mods, trig) in self._hotkeys.items()
            )
            log(f"keyboard hook installed (toggle+esc) — {active}")
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
            self._consumed.clear()

    def _reset_active_mode(self) -> None:
        """Clear the active-mode flag. Used when the start callback aborted
        early (e.g. model not loaded) so the next press isn't treated as stop."""
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
        try:
            return self._on_event_impl(event)
        except Exception as e:
            # Never block the keyboard because of our bug.
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

        # --- KEY UP -------------------------------------------------------
        if etype == "up":
            self._pressed.discard(key)
            self._consumed.discard(key)
            return True

        # --- KEY DOWN -----------------------------------------------------
        if etype != "down":
            return True

        # ESC: if a mode is currently active, stop it. Always let Esc
        # propagate (important — Esc closes dialogs elsewhere).
        if key == "esc":
            with self._lock:
                if self._active_mode is None:
                    return True
                mode = self._active_mode
                self._active_mode = None
                # Re-arm any trigger we were tracking so the next press starts fresh.
                self._consumed.clear()
            self._dispatch(self._on_stop, mode)
            return True

        self._pressed.add(key)

        # Auto-repeat: we've already acted on this key — keep suppressing
        # it (so the trigger key STILL doesn't leak) but don't re-toggle.
        if key in self._consumed:
            if self._is_trigger_key_for_any_registered_hotkey(key):
                return False
            return True

        # Check whether this press completes any registered hotkey.
        with self._lock:
            match_mode = None
            for mode, (mods, trigger) in self._hotkeys.items():
                if key == trigger and mods.issubset(self._pressed):
                    match_mode = mode
                    break

            if match_mode is None:
                return True  # unrelated key, let through

            # Mark consumed so auto-repeats of this physical press are ignored.
            self._consumed.add(key)

            if self._active_mode is None:
                # Toggle ON
                self._active_mode = match_mode
                dispatch_fn = self._on_start
                dispatch_mode = match_mode
            elif self._active_mode == match_mode:
                # Toggle OFF (same hotkey hit again)
                dispatch_fn = self._on_stop
                dispatch_mode = self._active_mode
                self._active_mode = None
            else:
                # Different mode is active → ignore (user must stop current first).
                # Still suppress so the trigger key doesn't leak.
                return False

        self._dispatch(dispatch_fn, dispatch_mode)
        return False  # always suppress a trigger-key press

    def _is_trigger_key_for_any_registered_hotkey(self, key: str) -> bool:
        for _mode, (_mods, trigger) in self._hotkeys.items():
            if key == trigger:
                return True
        return False

    def _dispatch(self, fn: Callable[[int], None], mode: int) -> None:
        """Fire a callback off the hook thread so the keyboard driver
        doesn't block on our Qt work."""
        threading.Thread(
            target=self._safe_call, args=(fn, mode), daemon=True
        ).start()

    @staticmethod
    def _safe_call(fn: Callable, arg) -> None:
        try:
            fn(arg)
        except Exception as e:
            try:
                log(f"hotkey callback {fn.__name__} raised {type(e).__name__}: {e}")
            except Exception:
                pass
