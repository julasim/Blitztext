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


def _preload_heavy_imports_synchronously() -> None:
    """Import all the heavy ML libs on the MAIN thread, BEFORE we start
    serving RPCs. This blocks startup by ~10–25 s on first launch but is
    the only reliable way to avoid Python import deadlocks: scipy + torch
    + pyannote pull in C extensions that do not survive concurrent
    cross-thread imports on Windows. We saw the preload-on-thread
    approach deadlock in scipy.signal load.

    All exceptions are caught and logged — sidecar must still start so
    the UI can surface the problem (and lighter RPCs like ping still work).
    """
    log = logging.getLogger("sidecar.preload")
    try:
        log.info("eager-importing torch...")
        import torch  # noqa: F401
        log.info("eager-importing faster_whisper.audio...")
        from faster_whisper.audio import decode_audio  # noqa: F401
        log.info("eager-importing pyannote pipeline...")
        from sidecar.diarization import DiarizationPipeline

        DiarizationPipeline.instance().ensure_loaded()
        log.info(
            "preload complete (device=%s)",
            DiarizationPipeline.instance().device,
        )
    except Exception as e:  # noqa: BLE001 — never crash startup
        log.warning("preload failed (non-fatal): %s", e)


def main() -> int:
    _force_utf8_stdio()
    log_path = _setup_logging()
    log = logging.getLogger("sidecar")
    log.info("Blitztext sidecar v%s starting (log: %s)", rpc.__version__, log_path)

    _preload_heavy_imports_synchronously()

    # Warteschlange starten. Sammelt zuerst Jobs ein, die beim letzten Lauf
    # auf "running" standen — die kann es nur nach einem Absturz geben, weil
    # genau ein Prozess die DB besitzt.
    try:
        from sidecar.jobs import JobQueue

        recovered = JobQueue.instance().start()
        if recovered.get("requeued") or recovered.get("failed"):
            log.warning(
                "Warteschlange nach Absturz aufgeräumt: %d neu eingereiht, %d aufgegeben",
                recovered["requeued"], recovered["failed"],
            )
    except Exception:  # noqa: BLE001 — ohne Queue läuft der Rest weiter
        log.exception("Job-Warteschlange konnte nicht gestartet werden")

    log.info("preload phase done; entering serve_stdio loop")

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
