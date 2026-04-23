"""RPC method implementations — import this to register handlers.

Kept separate from ``sidecar/rpc.py`` so the transport layer stays clean
and the methods can grow independently. Importing this module triggers
all ``@method`` decorators as import-side-effects.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from core.llm import cleanup_turn
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
    """Läuft den LLM-Cleanup über alle Turns eines Meetings.

    Synchron in dieser Phase — ein 200-Turn-Meeting braucht ~3 Min.
    Events für Streaming-Progress kommen mit der Pipeline (Phase 1 Ende).
    Idempotent: bereits bereinigte Turns werden übersprungen.

    Returns ``{ok, processed, skipped, total}``.
    """
    meeting_store.init_db()
    m = meeting_store.get_meeting(meeting_id)
    if m is None:
        raise RpcError(APP_NOT_FOUND, f"meeting {meeting_id} not found")

    turns = m["turns"]
    total = len(turns)
    processed = 0
    skipped = 0

    for i, t in enumerate(turns):
        if t.get("text_clean"):
            skipped += 1
            continue

        prev_text = turns[i - 1].get("text_clean") or turns[i - 1]["text_raw"] if i > 0 else None
        next_text = turns[i + 1]["text_raw"] if i + 1 < total else None

        try:
            cleaned = cleanup_turn(
                t["text_raw"], prev_text=prev_text, next_text=next_text, model=model
            )
        except Exception as e:
            # Einzelner Turn-Fehler stoppt den Lauf nicht — restliche Turns
            # sollen weiter versucht werden.
            raise RpcError(-32005, f"cleanup failed on turn {t['idx']}: {e}") from e

        meeting_store.set_turn_clean(t["id"], cleaned)
        processed += 1

    return {"ok": True, "total": total, "processed": processed, "skipped": skipped}


# --- Export ----------------------------------------------------------------


def _format_timestamp(ms: int) -> str:
    s = ms // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _meeting_to_markdown(m: dict, use_cleanup: bool) -> str:
    speaker_by_id = {s["id"]: s for s in m["speakers"]}
    lines: list[str] = []
    lines.append(f"# {m['title']}")
    lines.append("")
    created = m.get("created_at") or ""
    duration = _format_timestamp(int(m.get("duration_ms") or 0))
    language = m.get("language") or "—"
    model = m.get("whisper_model") or "—"
    lines.append(f"- **Datum:** {created}")
    lines.append(f"- **Dauer:** {duration}")
    lines.append(f"- **Sprache:** {language}")
    lines.append(f"- **Modell:** {model}")
    lines.append(f"- **Sprecher:** {len(m['speakers'])}")
    lines.append("")

    if m["speakers"]:
        lines.append("## Sprecher")
        lines.append("")
        for s in m["speakers"]:
            name = s.get("name") or s["label"]
            share = s.get("share_pct") or 0
            words = s.get("word_count") or 0
            lines.append(f"- **{name}** — {share}% ({words} Wörter)")
        lines.append("")

    lines.append("## Transkript")
    lines.append("")
    for t in m["turns"]:
        speaker = speaker_by_id.get(t["speaker_id"])
        name = (speaker.get("name") if speaker else None) or (
            speaker.get("label") if speaker else "Unbekannt"
        )
        ts = _format_timestamp(t["start_ms"])
        text = (t.get("text_clean") if use_cleanup else None) or t["text_raw"]
        flag = " ⚠︎ überlappende Rede" if t.get("overlap_flag") else ""
        lines.append(f"**[{ts}] {name}**{flag}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


@method("export.markdown")
def export_markdown(meeting_id: str, path: str, use_cleanup: bool = False) -> dict:
    """Schreibt ein Meeting als Markdown an ``path``."""
    meeting_store.init_db()
    m = meeting_store.get_meeting(meeting_id)
    if m is None:
        raise RpcError(APP_NOT_FOUND, f"meeting {meeting_id} not found")

    md = _meeting_to_markdown(m, use_cleanup=use_cleanup)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = md.encode("utf-8")
    out.write_bytes(data)
    return {"ok": True, "bytes": len(data), "path": str(out.resolve())}
