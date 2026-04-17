import threading
from typing import Callable
import keyboard


class HotkeyListener:
    """Listens for global hotkeys. Each mode has its own hotkey.

    Hold-to-record: on_press starts recording, on_release stops.
    """

    def __init__(
        self,
        on_start: Callable[[int], None],
        on_stop: Callable[[int], None],
    ):
        self._on_start = on_start
        self._on_stop = on_stop
        self._hotkeys: dict[str, int] = {}  # hotkey_str -> mode
        self._hooks: list = []
        self._active_mode: int | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._release_hook = None

    def register(self, hotkey_str: str, mode: int) -> None:
        """Register a hotkey for a mode. Deregisters any previous hotkey for that mode."""
        with self._lock:
            old_keys = [k for k, m in self._hotkeys.items() if m == mode]
            for k in old_keys:
                del self._hotkeys[k]
            self._hotkeys[hotkey_str] = mode

    def deregister_mode(self, mode: int) -> None:
        with self._lock:
            old_keys = [k for k, m in self._hotkeys.items() if m == mode]
            for k in old_keys:
                del self._hotkeys[k]

    def start(self) -> None:
        """Start listening. Blocks until stop() is called."""
        self._stop_hooks()

        with self._lock:
            hotkeys_snapshot = dict(self._hotkeys)

        for hotkey_str, mode in hotkeys_snapshot.items():
            try:
                hook_press = keyboard.add_hotkey(
                    hotkey_str,
                    self._handle_press,
                    args=(mode,),
                    suppress=True,
                    trigger_on_release=False,
                )
                self._hooks.append(hook_press)
            except Exception:
                pass

        self._release_hook = keyboard.on_release(self._handle_key_release)

        # Block this thread until stop() is called
        self._stop_event.clear()
        self._stop_event.wait()

    def stop(self) -> None:
        self._stop_event.set()
        self._stop_hooks()

    def _stop_hooks(self) -> None:
        for hook in self._hooks:
            try:
                keyboard.remove_hotkey(hook)
            except Exception:
                pass
        self._hooks.clear()
        if self._release_hook is not None:
            try:
                keyboard.unhook(self._release_hook)
            except Exception:
                pass
            self._release_hook = None

    def _handle_press(self, mode: int) -> None:
        with self._lock:
            if self._active_mode is not None:
                return
            self._active_mode = mode
        self._on_start(mode)

    def _handle_key_release(self, event) -> None:
        fire_stop = False
        mode = None

        with self._lock:
            if self._active_mode is None:
                return

            active_hotkey = None
            for hk, m in self._hotkeys.items():
                if m == self._active_mode:
                    active_hotkey = hk
                    break
            if active_hotkey is None:
                return

            parts = [p.strip().lower() for p in active_hotkey.replace("+", " ").split()]
            released = event.name.lower()

            normalize = {
                "strg": "ctrl", "steuerung": "ctrl",
                "left ctrl": "ctrl", "right ctrl": "ctrl",
                "umschalt": "shift", "umsch": "shift",
                "left shift": "shift", "right shift": "shift",
                "left alt": "alt", "right alt": "alt",
                "left windows": "windows", "right windows": "windows",
            }
            released_norm = normalize.get(released, released)
            parts_norm = [normalize.get(p, p) for p in parts]

            if released_norm in parts_norm:
                mode = self._active_mode
                self._active_mode = None
                fire_stop = True

        # Call on_stop OUTSIDE the lock
        if fire_stop:
            self._on_stop(mode)

    def update_hotkey(self, mode: int, new_hotkey: str) -> None:
        """Update a hotkey at runtime: deregister old, register new."""
        self.deregister_mode(mode)
        self.register(new_hotkey, mode)
