"""Entry point: `python -m sidecar` starts the RPC server.

When bundled via PyInstaller, this becomes `blitztext-sidecar.exe`. The
Tauri shell spawns that binary and communicates via stdin/stdout.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from sidecar import rpc

# Side-effect import: registers all @method handlers (config.get,
# meeting.*, speaker.*, cleanup.*, …). Keep this after rpc so the
# decorator is available.
from sidecar import methods  # noqa: F401


def _setup_logging() -> Path:
    """Log to %APPDATA%\\Blitztext\\sidecar.log so a production run leaves
    a post-mortem trail even when there's no console attached."""
    appdata = os.environ.get("APPDATA") or str(Path.home())
    log_dir = Path(appdata) / "Blitztext"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "sidecar.log"

    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return log_path


def _force_utf8_stdio() -> None:
    """The Tauri-side reader thread is strict UTF-8. Windows Python defaults
    to cp1252 on stdout/stderr unless the parent sets PYTHONIOENCODING. Be
    defensive — if any code path emits an umlaut or em-dash we don't want
    the bridge to die. Python 3.7+ supports reconfigure()."""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass


def main() -> int:
    _force_utf8_stdio()
    log_path = _setup_logging()
    log = logging.getLogger("sidecar")
    log.info("Blitztext sidecar v%s starting (log: %s)", rpc.__version__, log_path)

    try:
        rpc.serve_stdio()
    except KeyboardInterrupt:
        log.info("sidecar: KeyboardInterrupt, shutting down")
        return 130
    except Exception:  # noqa: BLE001 — we log the full traceback
        log.exception("sidecar: fatal error")
        return 1

    log.info("sidecar: stdin closed, exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
