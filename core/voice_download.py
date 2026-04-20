"""Download Piper TTS voice models from HuggingFace into the user's
AppData voices folder.

A Piper voice is two files: ``<voice_id>.onnx`` (the model, ~15–65 MB)
and ``<voice_id>.onnx.json`` (a few KB of config). We download the
large ``.onnx`` with real byte-level progress, then the small JSON
without a progress bar (done in a blink).

Files land next to the Whisper models, under
``%APPDATA%\\Blitztext\\voices\\``. They're written to ``.part`` files
first and renamed on success so a crashed download can never leave a
truncated voice that would then fail to load silently.
"""

import os
from typing import Callable, Optional

import httpx

from config.defaults import PIPER_VOICES
from core.log import log


def voices_dir() -> str:
    """Absolute path to the voices cache. Created on demand."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    path = os.path.join(appdata, "Blitztext", "voices")
    os.makedirs(path, exist_ok=True)
    return path


def voice_paths(voice_id: str) -> tuple[str, str]:
    """Return (onnx_path, json_path) for a cached voice. Files may not exist yet."""
    base = os.path.join(voices_dir(), voice_id)
    return base + ".onnx", base + ".onnx.json"


def is_voice_installed(voice_id: str) -> bool:
    """Both files present and non-empty."""
    onnx, js = voice_paths(voice_id)
    return (
        os.path.isfile(onnx) and os.path.getsize(onnx) > 0
        and os.path.isfile(js) and os.path.getsize(js) > 0
    )


def download_voice(
    voice_id: str,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    """Fetch the ``.onnx`` + ``.onnx.json`` for ``voice_id``.

    ``on_progress(done_bytes, total_bytes, label)`` is called repeatedly
    during the ``.onnx`` stream so a UI can show a live progress bar.
    Raises on network / IO errors; the caller is expected to show the
    user a meaningful message.
    """
    meta = PIPER_VOICES.get(voice_id)
    if meta is None:
        raise ValueError(f"Unbekannte Piper-Stimme: {voice_id}")

    onnx_path, json_path = voice_paths(voice_id)
    label = meta.get("label", voice_id)

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        # --- 1. The large ONNX model, with progress ---
        _stream_with_progress(
            client, meta["onnx_url"], onnx_path,
            on_progress=on_progress, label=label,
        )

        # --- 2. The small JSON config ---
        if on_progress is not None:
            try:
                on_progress(0, 0, f"{label} (Config)")
            except Exception:
                pass
        r = client.get(meta["json_url"])
        r.raise_for_status()
        tmp = json_path + ".part"
        with open(tmp, "wb") as f:
            f.write(r.content)
        if os.path.exists(json_path):
            os.remove(json_path)
        os.rename(tmp, json_path)
        log(f"voice_download: installed {voice_id} → {onnx_path}")


def _stream_with_progress(
    client: httpx.Client,
    url: str,
    dest: str,
    on_progress: Optional[Callable[[int, int, str], None]],
    label: str,
) -> None:
    tmp = dest + ".part"
    try:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0"))
            done = 0
            if on_progress is not None:
                try:
                    on_progress(0, total, label)
                except Exception:
                    pass
            with open(tmp, "wb") as f:
                last_logged_mb = 0
                for chunk in r.iter_bytes(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        try:
                            on_progress(done, total, label)
                        except Exception:
                            pass
                    done_mb = done // (10 * 1024 * 1024)
                    if done_mb > last_logged_mb:
                        last_logged_mb = done_mb
                        log(
                            f"voice download {label}: "
                            f"{done/1_000_000:.0f} / {total/1_000_000:.0f} MB"
                        )
        if os.path.exists(dest):
            os.remove(dest)
        os.rename(tmp, dest)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise
