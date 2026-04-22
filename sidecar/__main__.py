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


def main() -> int:
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
