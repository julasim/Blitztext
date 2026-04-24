"""SQLite persistence for meetings, speakers, and turns.

Schema (single source of truth — kept in sync with sidecar/rpc_schema.md):

    meetings(id, title, audio_path, duration_ms, language, created_at,
             status, whisper_model, diar_model)
    speakers(id, meeting_id -> meetings, label, name, color,
             word_count, duration_ms, share_pct)
    turns(id, meeting_id -> meetings, speaker_id -> speakers,
          idx, start_ms, end_ms, text_raw, text_clean, words_json, overlap_flag)

The DB lives at ``%APPDATA%\\Blitztext\\meetings.db`` and per-meeting audio
under ``%APPDATA%\\Blitztext\\meetings\\<uuid>\\``.

Design notes
------------
- Single module-level connection, opened lazily. SQLite is file-locked, so
  the single-process sidecar model is safe.
- ``PRAGMA foreign_keys = ON`` must be set per connection — SQLite does NOT
  persist this setting.
- Speaker stats (word_count, duration_ms, share_pct) are denormalized on
  ingest so list/get reads don't need subqueries.
- No migration framework yet; schema_version pragma + bespoke steps when
  we need v2.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# --- Paths -----------------------------------------------------------------


def appdata_dir() -> Path:
    root = os.environ.get("APPDATA") or str(Path.home())
    p = Path(root) / "Blitztext"
    p.mkdir(parents=True, exist_ok=True)
    return p


def meetings_dir() -> Path:
    p = appdata_dir() / "meetings"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return appdata_dir() / "meetings.db"


def meeting_folder(meeting_id: str) -> Path:
    p = meetings_dir() / meeting_id
    p.mkdir(parents=True, exist_ok=True)
    return p


# --- Connection ------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meetings (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    audio_path    TEXT,
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    language      TEXT,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'processing',
    whisper_model TEXT,
    diar_model    TEXT
);

CREATE TABLE IF NOT EXISTS speakers (
    id          TEXT PRIMARY KEY,
    meeting_id  TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    name        TEXT,
    color       TEXT NOT NULL,
    word_count  INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    share_pct   REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
    id           TEXT PRIMARY KEY,
    meeting_id   TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    speaker_id   TEXT REFERENCES speakers(id) ON DELETE SET NULL,
    idx          INTEGER NOT NULL,
    start_ms     INTEGER NOT NULL,
    end_ms       INTEGER NOT NULL,
    text_raw     TEXT NOT NULL,
    text_clean   TEXT,
    words_json   TEXT NOT NULL DEFAULT '[]',
    overlap_flag INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_turns_meeting_idx ON turns(meeting_id, idx);
CREATE INDEX IF NOT EXISTS idx_speakers_meeting ON speakers(meeting_id);
"""

_SCHEMA_VERSION = 1

_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    conn = sqlite3.connect(str(db_path()), isolation_level=None)  # autocommit off via explicit BEGIN
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION};")
    conn.executescript(_SCHEMA_SQL)
    _conn = conn
    return conn


def close() -> None:
    """Close the connection. Called on shutdown; tests also use this."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def init_db() -> None:
    """Idempotent — ensures the schema exists. Safe to call at startup."""
    _connect()


# --- Speaker colors --------------------------------------------------------
# 12-color palette from the design handoff. Round-robin assignment in
# insertion order gives stable, distinguishable speaker colors.
SPEAKER_PALETTE: tuple[str, ...] = (
    "#09090b",  # ink
    "#ef4444",  # red
    "#f59e0b",  # amber
    "#10b981",  # emerald
    "#3b82f6",  # blue
    "#8b5cf6",  # violet
    "#ec4899",  # pink
    "#14b8a6",  # teal
    "#f97316",  # orange
    "#6366f1",  # indigo
    "#84cc16",  # lime
    "#06b6d4",  # cyan
)


def palette_color(n: int) -> str:
    return SPEAKER_PALETTE[n % len(SPEAKER_PALETTE)]


# --- Helpers ---------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return str(uuid.uuid4())


# --- Meetings --------------------------------------------------------------


def create_meeting(
    *,
    title: str,
    audio_path: str | None = None,
    duration_ms: int = 0,
    language: str | None = None,
    whisper_model: str | None = None,
    diar_model: str | None = None,
    status: str = "processing",
) -> str:
    """Insert a new meeting row. Returns the generated id."""
    conn = _connect()
    mid = _new_id()
    conn.execute(
        "INSERT INTO meetings "
        "(id, title, audio_path, duration_ms, language, created_at, status, "
        " whisper_model, diar_model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            mid,
            title,
            audio_path,
            int(duration_ms),
            language,
            _now_iso(),
            status,
            whisper_model,
            diar_model,
        ),
    )
    return mid


def set_title(meeting_id: str, title: str) -> bool:
    conn = _connect()
    cur = conn.execute(
        "UPDATE meetings SET title = ? WHERE id = ?", (title, meeting_id)
    )
    return cur.rowcount > 0


def set_status(meeting_id: str, status: str) -> None:
    conn = _connect()
    conn.execute("UPDATE meetings SET status = ? WHERE id = ?", (status, meeting_id))


def set_duration(meeting_id: str, duration_ms: int) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE meetings SET duration_ms = ? WHERE id = ?",
        (int(duration_ms), meeting_id),
    )


def set_audio_path(meeting_id: str, audio_path: str) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE meetings SET audio_path = ? WHERE id = ?",
        (audio_path, meeting_id),
    )


def set_language(meeting_id: str, language: str) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE meetings SET language = ? WHERE id = ?",
        (language, meeting_id),
    )


def list_meetings(limit: int = 100, offset: int = 0) -> list[dict]:
    """Newest first. Returns MeetingListItem dicts (no speakers/turns)."""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, title, duration_ms, created_at, status "
        "FROM meetings ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (int(limit), int(offset)),
    ).fetchall()
    return [dict(r) for r in rows]


def get_meeting(meeting_id: str) -> dict | None:
    """Full meeting with speakers and turns. None if unknown."""
    conn = _connect()
    m = conn.execute(
        "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
    ).fetchone()
    if m is None:
        return None

    speakers = [
        dict(r)
        for r in conn.execute(
            "SELECT id, label, name, color, word_count, duration_ms, share_pct "
            "FROM speakers WHERE meeting_id = ? ORDER BY label",
            (meeting_id,),
        ).fetchall()
    ]

    turn_rows = conn.execute(
        "SELECT id, speaker_id, idx, start_ms, end_ms, text_raw, text_clean, "
        "words_json, overlap_flag "
        "FROM turns WHERE meeting_id = ? ORDER BY idx ASC",
        (meeting_id,),
    ).fetchall()
    turns = []
    for r in turn_rows:
        t = dict(r)
        t["words"] = json.loads(t.pop("words_json") or "[]")
        t["overlap_flag"] = bool(t["overlap_flag"])
        turns.append(t)

    out = dict(m)
    out["speakers"] = speakers
    out["turns"] = turns
    return out


def delete_meeting(meeting_id: str) -> bool:
    """Removes DB rows (CASCADE) and the audio folder on disk."""
    conn = _connect()
    cur = conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
    folder = meetings_dir() / meeting_id
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return cur.rowcount > 0


# --- Speakers --------------------------------------------------------------


def upsert_speakers(meeting_id: str, speakers: Iterable[dict]) -> None:
    """Replace all speakers for a meeting. Callers provide dicts with keys:
    label, name?, color?, word_count?, duration_ms?, share_pct?

    IDs are assigned here if missing. Colors default to the palette round-robin.
    """
    conn = _connect()
    with _transaction(conn):
        conn.execute("DELETE FROM speakers WHERE meeting_id = ?", (meeting_id,))
        for i, sp in enumerate(speakers):
            sid = sp.get("id") or _new_id()
            conn.execute(
                "INSERT INTO speakers "
                "(id, meeting_id, label, name, color, word_count, "
                " duration_ms, share_pct) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sid,
                    meeting_id,
                    sp.get("label") or f"Speaker {i+1}",
                    sp.get("name"),
                    sp.get("color") or palette_color(i),
                    int(sp.get("word_count") or 0),
                    int(sp.get("duration_ms") or 0),
                    float(sp.get("share_pct") or 0.0),
                ),
            )


def rename_speaker(meeting_id: str, speaker_id: str, name: str) -> bool:
    conn = _connect()
    cur = conn.execute(
        "UPDATE speakers SET name = ? WHERE id = ? AND meeting_id = ?",
        (name, speaker_id, meeting_id),
    )
    return cur.rowcount > 0


def merge_speakers(meeting_id: str, source_id: str, target_id: str) -> int:
    """Reassign all turns from source → target, then delete source speaker.
    Returns the count of reassigned turns.

    Stats on the target are NOT recomputed here — the caller (pipeline or
    a dedicated recompute function) should refresh word_count / duration_ms
    / share_pct afterwards if needed.
    """
    if source_id == target_id:
        return 0
    conn = _connect()
    with _transaction(conn):
        cur = conn.execute(
            "UPDATE turns SET speaker_id = ? "
            "WHERE meeting_id = ? AND speaker_id = ?",
            (target_id, meeting_id, source_id),
        )
        moved = cur.rowcount
        conn.execute(
            "DELETE FROM speakers WHERE id = ? AND meeting_id = ?",
            (source_id, meeting_id),
        )
    return moved


# --- Turns -----------------------------------------------------------------


def upsert_turns(meeting_id: str, turns: Sequence[dict]) -> None:
    """Replace all turns for a meeting. Each turn dict expects:
    speaker_id, idx, start_ms, end_ms, text_raw,
    text_clean? (default None), words? (default []), overlap_flag? (default False).
    """
    conn = _connect()
    with _transaction(conn):
        conn.execute("DELETE FROM turns WHERE meeting_id = ?", (meeting_id,))
        rows = []
        for t in turns:
            rows.append(
                (
                    t.get("id") or _new_id(),
                    meeting_id,
                    t.get("speaker_id"),
                    int(t["idx"]),
                    int(t["start_ms"]),
                    int(t["end_ms"]),
                    t["text_raw"],
                    t.get("text_clean"),
                    json.dumps(t.get("words") or [], ensure_ascii=False),
                    1 if t.get("overlap_flag") else 0,
                )
            )
        if rows:
            conn.executemany(
                "INSERT INTO turns "
                "(id, meeting_id, speaker_id, idx, start_ms, end_ms, "
                " text_raw, text_clean, words_json, overlap_flag) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )


def set_turn_clean(turn_id: str, text_clean: str) -> bool:
    conn = _connect()
    cur = conn.execute(
        "UPDATE turns SET text_clean = ? WHERE id = ?", (text_clean, turn_id)
    )
    return cur.rowcount > 0


# --- Transactions ----------------------------------------------------------


class _TxnCtx:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")


def _transaction(conn: sqlite3.Connection) -> _TxnCtx:
    return _TxnCtx(conn)
