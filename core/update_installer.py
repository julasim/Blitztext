"""Download the new installer and launch it. The installer will stop the running
VoiceType, replace the files, and start the fresh version automatically.
"""

import os
import subprocess
import tempfile
from typing import Callable, Optional

import httpx

from core.log import log


def download_installer(
    url: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> str:
    """Download the installer to a temp file and return the path.

    progress_callback(bytes_done, bytes_total) is called during the download.
    The temp file is removed if the download fails.
    """
    fd, path = tempfile.mkstemp(prefix="VoiceType-Setup-", suffix=".exe")
    os.close(fd)

    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=None) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0"))
            done = 0
            with open(path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_callback is not None:
                        try:
                            progress_callback(done, total)
                        except Exception:
                            pass
        return path
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass
        raise


def launch_installer_and_quit(installer_path: str) -> None:
    """Start the installer detached, then quit this process.

    The installer runs in /VERYSILENT mode: no UI, automatic replace, and the
    [Run] entry in voicetype.iss launches the new VoiceType.exe afterwards.
    """
    DETACHED = 0x00000008
    NEW_GROUP = 0x00000200
    try:
        subprocess.Popen(
            [installer_path, "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            creationflags=DETACHED | NEW_GROUP,
            close_fds=True,
        )
        # Installer runs detached — safe to exit immediately.
    except Exception as e:
        log(f"Installer launch failed: {e}")
    finally:
        os._exit(0)
