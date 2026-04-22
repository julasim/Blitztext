"""RPC method implementations — import this to register handlers.

Kept separate from ``sidecar/rpc.py`` so the transport layer stays clean
and the methods can grow independently. Importing this module triggers
all ``@method`` decorators as import-side-effects.
"""

from __future__ import annotations

import os

import httpx

from sidecar import meeting_store
from sidecar.rpc import APP_NOT_FOUND, RpcError, method


# --- Meta / config ---------------------------------------------------------


def _ollama_available() -> bool:
    """Quick probe — 500ms timeout so we never block startup."""
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=0.5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _cuda_available() -> bool:
    """Torch may not be installed yet (Phase 0). Report False until the
    heavy deps land."""
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        return False


@method("config.get")
def config_get() -> dict:
    return {
        "appdata": str(meeting_store.appdata_dir()),
        "models_dir": str(meeting_store.appdata_dir() / "models"),
        "meetings_dir": str(meeting_store.meetings_dir()),
        "db_path": str(meeting_store.db_path()),
        "cuda_available": _cuda_available(),
        "ollama_available": _ollama_available(),
        "whisper_models": ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
        "python_executable": os.environ.get("VIRTUAL_ENV", "system"),
    }


# --- Meetings --------------------------------------------------------------


@method("meeting.list")
def meeting_list(limit: int = 100, offset: int = 0) -> list[dict]:
    meeting_store.init_db()
    return meeting_store.list_meetings(limit=limit, offset=offset)


@method("meeting.get")
def meeting_get(id: str) -> dict:
    meeting_store.init_db()
    m = meeting_store.get_meeting(id)
    if m is None:
        raise RpcError(APP_NOT_FOUND, f"meeting {id} not found")
    return m


@method("meeting.delete")
def meeting_delete(id: str) -> dict:
    meeting_store.init_db()
    ok = meeting_store.delete_meeting(id)
    if not ok:
        raise RpcError(APP_NOT_FOUND, f"meeting {id} not found")
    return {"ok": True}


@method("meeting.set_title")
def meeting_set_title(id: str, title: str) -> dict:
    meeting_store.init_db()
    ok = meeting_store.set_title(id, title)
    if not ok:
        raise RpcError(APP_NOT_FOUND, f"meeting {id} not found")
    return {"ok": True}


# --- Speakers --------------------------------------------------------------


@method("speaker.rename")
def speaker_rename(meeting_id: str, speaker_id: str, name: str) -> dict:
    meeting_store.init_db()
    ok = meeting_store.rename_speaker(meeting_id, speaker_id, name)
    if not ok:
        raise RpcError(APP_NOT_FOUND, f"speaker {speaker_id} not found")
    return {"ok": True}


@method("speaker.merge")
def speaker_merge(meeting_id: str, source_id: str, target_id: str) -> dict:
    meeting_store.init_db()
    moved = meeting_store.merge_speakers(meeting_id, source_id, target_id)
    return {"ok": True, "merged_turns": moved}


# --- Pipeline (stubs — real implementations come with pyannote+whisper) ----


@method("meeting.import_file")
def meeting_import_file(path: str, title: str | None = None) -> dict:
    """Phase 1 target. Stub raises until the pipeline lands."""
    raise RpcError(
        -32003,
        "meeting.import_file not implemented yet — pending heavy deps (torch+pyannote)",
    )


@method("cleanup.run")
def cleanup_run(meeting_id: str, model: str | None = None) -> dict:
    raise RpcError(
        -32003, "cleanup.run not implemented yet — pending Ollama-local wiring"
    )
