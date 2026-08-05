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
    except Exception:  # noqa: BLE001 — never crash startup
        # Mit vollem Traceback: ohne ihn steht im Log nur die Wortmeldung der
        # obersten Ebene, und die verdeckt gerade beim gebündelten Sidecar,
        # WORAN der Import wirklich gescheitert ist.
        log.warning("preload failed (non-fatal)", exc_info=True)


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
    finally:
        # Warteschlange geordnet anhalten. Ohne das bleibt ein laufender Job
        # auf "running" stehen; der nächste Start hält das für einen Absturz
        # und verbraucht einen der zwei Versuche. Zweimal die App während
        # desselben Imports schließen hätte die Datei sonst endgültig als
        # "bringt den Import reproduzierbar zum Absturz" abgestempelt.
        _stop_queue(log)

    log.info("sidecar: stdin closed, exiting cleanly")
    return 0


def _stop_queue(log: logging.Logger) -> None:
    """Worker anhalten und laufenden Job wieder freigeben."""
    try:
        from sidecar.jobs import JobQueue

        JobQueue.instance().shutdown()
    except Exception:  # noqa: BLE001 — Herunterfahren darf nie werfen
        log.exception("Warteschlange konnte nicht geordnet angehalten werden")


if __name__ == "__main__":
    sys.exit(main())
