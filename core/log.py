"""Tiny rolling log file in %APPDATA%\\Blitztext\\blitztext.log for post-mortem diagnostics."""

import os
import threading
from datetime import datetime


_LOCK = threading.Lock()
_PATH = None


def _path() -> str:
    global _PATH
    if _PATH is None:
        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        folder = os.path.join(appdata, "Blitztext")
        os.makedirs(folder, exist_ok=True)
        _PATH = os.path.join(folder, "blitztext.log")
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


