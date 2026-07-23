"""RPC method implementations — import this to register handlers.

Kept separate from ``sidecar/rpc.py`` so the transport layer stays clean
and the methods can grow independently. Importing this module triggers
all ``@method`` decorators as import-side-effects.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

import threading

from core.llm import cleanup_turn
from sidecar import meeting_store
from sidecar.rpc import APP_NOT_FOUND, RpcError, emit_event, method


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
def meeting_import_file(
    path: str,
    title: str | None = None,
    language: str = "de",
    whisper_model: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> dict:
    """Datei in die Warteschlange stellen.

    Gibt ``meeting_id`` (und ``job_id``) sofort zurück; die fünf Stages
    laufen im Queue-Worker und melden sich über ``meeting.progress`` /
    ``meeting.done`` / ``meeting.error`` sowie die ``queue.*``-Events.

    Historisch startete diese Methode direkt einen Thread. Seit der
    Warteschlange läuft **immer nur ein Import gleichzeitig** — zwei
    parallele Läufe teilten sich sonst Whisper-Cache und GPU.
    """
    import logging

    log = logging.getLogger("sidecar.import")
    log.info("meeting.import_file: path=%r title=%r model=%r", path, title, whisper_model)

    from sidecar.jobs import JobQueue

    try:
        result = JobQueue.instance().enqueue(
            path,
            title=title,
            language=language,
            whisper_model=whisper_model,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
        )
    except FileNotFoundError as e:
        log.warning("meeting.import_file FileNotFoundError: %s", e)
        raise RpcError(APP_NOT_FOUND, str(e)) from e
    except Exception as e:
        log.exception("meeting.import_file enqueue failed")
        raise RpcError(-32001, f"Import konnte nicht gestartet werden: {e}") from e

    return result


# --- Warteschlange ---------------------------------------------------------


@method("queue.list")
def queue_list(limit: int = 200) -> list[dict]:
    """Alle Jobs in Abarbeitungsreihenfolge."""
    from sidecar import jobs

    return jobs.list_jobs(limit=limit)


@method("queue.state")
def queue_state() -> dict:
    """Zähler je Zustand + der gerade laufende Job."""
    from sidecar.jobs import JobQueue

    return JobQueue.instance().state()


@method("queue.cancel")
def queue_cancel(job_id: str) -> dict:
    """Wartenden Job verwerfen oder laufenden zum Abbruch vormerken.

    Bei einem laufenden Job kommt ``{pending: true}`` zurück — der Abbruch
    greift am nächsten Prüfpunkt (Stage-Grenze oder Whisper-Segment).
    """
    from sidecar.jobs import JobQueue

    return JobQueue.instance().cancel(job_id)


@method("queue.clear_finished")
def queue_clear_finished() -> dict:
    """Erledigte, fehlgeschlagene und abgebrochene Einträge entfernen."""
    from sidecar.jobs import JobQueue

    return JobQueue.instance().clear_finished()


@method("cleanup.run")
def cleanup_run(meeting_id: str, model: str | None = None) -> dict:
    """Startet den LLM-Cleanup über alle Turns eines Meetings.

    Asynchron — RPC kehrt sofort zurück, Worker-Thread läuft die Turns
    durch und emittiert ``cleanup.progress`` / ``cleanup.done`` /
    ``cleanup.error`` Events. Idempotent: bereits bereinigte Turns
    werden übersprungen.

    Returns ``{ok, started, total}``.
    """
    import logging
    log = logging.getLogger("sidecar.cleanup")

    meeting_store.init_db()
    m = meeting_store.get_meeting(meeting_id)
    if m is None:
        raise RpcError(APP_NOT_FOUND, f"meeting {meeting_id} not found")

    total = len(m["turns"])
    log.info("cleanup.run start: meeting=%s turns=%d", meeting_id, total)

    def _worker() -> None:
        # Re-fetch turns inside the worker so we work with fresh state.
        meeting_store.init_db()
        m_fresh = meeting_store.get_meeting(meeting_id)
        if m_fresh is None:
            emit_event("cleanup.error", {"meeting_id": meeting_id, "message": "meeting disappeared"})
            return
        turns = m_fresh["turns"]
        n = len(turns)
        processed = 0
        skipped = 0

        for i, t in enumerate(turns):
            if t.get("text_clean"):
                skipped += 1
                emit_event(
                    "cleanup.progress",
                    {
                        "meeting_id": meeting_id,
                        "processed": processed,
                        "skipped": skipped,
                        "total": n,
                        "turn_id": t["id"],
                    },
                )
                continue

            prev_text = (
                turns[i - 1].get("text_clean") or turns[i - 1]["text_raw"]
                if i > 0 else None
            )
            next_text = turns[i + 1]["text_raw"] if i + 1 < n else None

            try:
                cleaned = cleanup_turn(
                    t["text_raw"],
                    prev_text=prev_text,
                    next_text=next_text,
                    model=model,
                )
            except Exception as e:
                log.warning("cleanup turn %s failed: %s", t["id"][:8], e)
                emit_event(
                    "cleanup.error",
                    {
                        "meeting_id": meeting_id,
                        "turn_id": t["id"],
                        "message": str(e),
                    },
                )
                # Don't break — keep going on subsequent turns.
                continue

            meeting_store.set_turn_clean(t["id"], cleaned)
            processed += 1
            emit_event(
                "cleanup.progress",
                {
                    "meeting_id": meeting_id,
                    "processed": processed,
                    "skipped": skipped,
                    "total": n,
                    "turn_id": t["id"],
                },
            )

        log.info(
            "cleanup.run done: meeting=%s processed=%d skipped=%d total=%d",
            meeting_id, processed, skipped, n,
        )
        emit_event(
            "cleanup.done",
            {
                "meeting_id": meeting_id,
                "processed": processed,
                "skipped": skipped,
                "total": n,
            },
        )

    threading.Thread(
        target=_worker, name=f"cleanup-{meeting_id[:8]}", daemon=True
    ).start()

    return {"ok": True, "started": True, "total": total}


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


# --- Settings (HF token, model defaults) -----------------------------------


@method("settings.get")
def settings_get() -> dict:
    """User-editable settings + derived hints for the UI.

    Token presence is reported as a boolean + last-4 character hint so
    the UI can show 'hf_…GkcW' without exposing the secret.
    """
    import keyring

    try:
        tok = keyring.get_password("Blitztext", "hf_token") or ""
    except Exception:
        tok = ""

    last4 = tok[-4:] if tok else ""
    return {
        "hf_token_present": bool(tok),
        "hf_token_hint": f"hf_…{last4}" if tok else "",
        "whisper_default": "large-v3-turbo",
        "ollama_default": "qwen2.5:7b-instruct",
    }


@method("settings.set_hf_token")
def settings_set_hf_token(token: str) -> dict:
    """Persist (or delete) the HuggingFace token in Windows Credential Manager."""
    import keyring

    token = (token or "").strip()
    if token:
        if not token.startswith("hf_") or len(token) < 20:
            raise RpcError(
                -32602,
                "Token sieht ungültig aus — sollte mit 'hf_' beginnen.",
            )
        keyring.set_password("Blitztext", "hf_token", token)
        return {"ok": True, "stored": True}

    # Empty string: delete the credential.
    try:
        keyring.delete_password("Blitztext", "hf_token")
    except Exception:
        pass  # already absent
    return {"ok": True, "stored": False}


@method("settings.test_hf_token")
def settings_test_hf_token() -> dict:
    """Probe HF with the stored token: auth + gated-repo access.

    The UI uses this to render a green/yellow/red status; without it the
    only feedback is a failed import 30 minutes in.
    """
    import keyring

    try:
        tok = keyring.get_password("Blitztext", "hf_token") or ""
    except Exception as e:
        raise RpcError(-32000, f"Keyring nicht erreichbar: {e}") from e

    if not tok:
        return {"ok": False, "stage": "missing", "message": "Kein Token gespeichert."}

    try:
        from huggingface_hub import HfApi, hf_hub_download  # type: ignore
    except ImportError:
        return {"ok": False, "stage": "deps", "message": "huggingface_hub fehlt."}

    api = HfApi()
    try:
        who = api.whoami(token=tok)
        user_name = who.get("name") if isinstance(who, dict) else str(who)
    except Exception as e:
        return {"ok": False, "stage": "auth", "message": f"Token ungültig: {e}"}

    # Gated-repo probe: try to fetch a small file from a known gated model.
    try:
        hf_hub_download(
            repo_id="pyannote/speaker-diarization-3.1",
            filename="config.yaml",
            token=tok,
        )
    except Exception as e:
        return {
            "ok": False,
            "stage": "gated",
            "user": user_name,
            "message": (
                "Token authentifiziert, aber keine Gated-Repo-Zugriffsrechte. "
                "Token unter huggingface.co/settings/tokens bearbeiten und "
                "'Read access to contents of all public gated repos you can "
                f"access' aktivieren. Detail: {e}"
            ),
        }

    return {
        "ok": True,
        "stage": "ready",
        "user": user_name,
        "message": f"Eingeloggt als {user_name}, Gated-Zugriff bestätigt.",
    }
