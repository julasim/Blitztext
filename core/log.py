"""Tiny rolling log file in %APPDATA%\\VoiceType\\voicetype.log for post-mortem diagnostics."""

import os
import threading
import traceback
from datetime import datetime


_LOCK = threading.Lock()
_PATH = None


def _path() -> str:
    global _PATH
    if _PATH is None:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        folder = os.path.join(appdata, "VoiceType")
        os.makedirs(folder, exist_ok=True)
        _PATH = os.path.join(folder, "voicetype.log")
    return _PATH


def log(msg: str) -> None:
    try:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"{stamp}  {msg}\n"
        with _LOCK:
            with open(_path(), "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def log_exc(context: str) -> None:
    try:
        log(f"{context}\n{traceback.format_exc()}")
    except Exception:
        pass


def reset() -> None:
    """Start a new log on app launch so we don't accumulate forever."""
    try:
        with _LOCK:
            with open(_path(), "w", encoding="utf-8") as f:
                f.write(f"=== VoiceType log started {datetime.now().isoformat()} ===\n")
    except Exception:
        pass
