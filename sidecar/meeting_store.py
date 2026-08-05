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
- Migrationen: nummerierte SQL-Schritte gegen ``PRAGMA user_version``,
  forward-only. Anleitung steht bei ``_MIGRATIONS``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
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

# --- Migrationen -----------------------------------------------------------
#
# Kein Alembic — nummerierte SQL-Schritte plus `PRAGMA user_version` als
# Zähler. Beim Öffnen wird die Version gelesen und jeder Schritt mit höherer
# Nummer genau einmal angewendet.
#
# NEUE MIGRATION HINZUFÜGEN:
#   1. Tupel `(N, "SQL…")` unten anhängen, N = bisheriges Maximum + 1.
#   2. SQL idempotent halten (`IF NOT EXISTS`), damit ein abgebrochener Lauf
#      wiederholbar bleibt.
#   3. Alte Schritte NIE ändern — bestehende DBs haben sie schon hinter sich.
#      Forward-only.
#
# Schritt 1 ist das Ausgangsschema. Es läuft auch gegen DBs, die vor der
# Einführung dieses Mechanismus entstanden sind: die tragen bereits
# `user_version = 1` und werden deshalb übersprungen.

# Schritt 2: Import-Warteschlange. Die Jobs liegen in der DB (nicht nur im
# Speicher), damit ein Absturz mitten im Stapel nachvollziehbar bleibt und
# unterbrochene Läufe beim nächsten Start wieder aufgenommen werden können.
_JOBS_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    -- Bewusst NULL-bar mit SET NULL: beim Abbruch verschwindet die leere
    -- Meeting-Hülle, der Job-Eintrag bleibt aber als Historie stehen.
    meeting_id  TEXT REFERENCES meetings(id) ON DELETE SET NULL,
    source_path TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    state       TEXT NOT NULL DEFAULT 'queued',
    position    INTEGER NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_state_pos ON jobs(state, position);
"""

# Schritt 3: Einstellungen als Schlüssel/Wert (das Fachvokabular ist
# mehrzeiliger Text — im Windows-Credential-Manager, wo der HF-Token liegt,
# wäre er fehl am Platz), plus die Cleanup-Stufe je Turn. Ohne die Stufe
# überspringt ein zweiter Cleanup-Lauf jeden bereits bereinigten Turn und
# ein Stufenwechsel bliebe wirkungslos.
_SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

ALTER TABLE turns ADD COLUMN text_clean_mode TEXT;
"""

_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, _SCHEMA_SQL),
    (2, _JOBS_SQL),
    (3, _SETTINGS_SQL),
)

_SCHEMA_VERSION = max(v for v, _ in _MIGRATIONS)

_conn: sqlite3.Connection | None = None


def _einzelstatements(sql: str) -> list[str]:
    """Zerlegt ein SQL-Skript in einzeln ausführbare Statements.

    Nötig, weil ``executescript`` vor dem ersten Statement implizit committet
    und damit jede umschließende Transaktion aufhebt — ein Migrationsschritt
    wäre dann nicht mehr unteilbar.
    """
    statements: list[str] = []
    puffer = ""
    for zeile in sql.splitlines(keepends=True):
        puffer += zeile
        if puffer.strip() and sqlite3.complete_statement(puffer):
            statements.append(puffer)
            puffer = ""
    if puffer.strip():
        statements.append(puffer)
    return statements


def _migrate(conn: sqlite3.Connection) -> int:
    """Wendet ausstehende Migrationen an. Gibt die erreichte Version zurück.

    Jeder Schritt läuft in einer eigenen Transaktion — SQLite kann auch DDL
    zurückrollen. Ohne das hinterlässt ein Absturz zwischen Schema-Änderung
    und Versionsstempel eine DB, die sich **nie wieder öffnen lässt**:
    ``ALTER TABLE … ADD COLUMN`` kennt kein ``IF NOT EXISTS``, der zweite
    Versuch scheitert also dauerhaft an „duplicate column name".
    """
    current = int(conn.execute("PRAGMA user_version;").fetchone()[0])
    for version, sql in _MIGRATIONS:
        if version <= current:
            continue
        conn.execute("BEGIN")
        try:
            for statement in _einzelstatements(sql):
                conn.execute(statement)
            # PRAGMA nimmt keine Parameter-Bindung — der Wert kommt aus einer
            # Konstante im Modul, nicht von außen.
            conn.execute(f"PRAGMA user_version = {version};")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        current = version
    return current


# Eine Verbindung, mehrere Threads (RPC-Dispatch, Job-Worker, Cleanup-Worker).
# Diese Sperre serialisiert JEDEN Zugriff darauf und wird von `_transaction()`
# über die gesamte Transaktion gehalten. RLock, damit die execute-Aufrufe
# innerhalb einer Transaktion aus demselben Thread durchkommen.
_db_lock = threading.RLock()


class _SerialisierteVerbindung:
    """sqlite3.Connection hinter ``_db_lock``.

    Der frühere Kommentar an dieser Stelle behauptete, wir teilten nie eine
    Transaktion über Threadgrenzen — das war falsch: Transaktionen gehören in
    SQLite der Verbindung, nicht dem Thread. Statt jede der rund dreißig
    Schreibstellen einzeln abzusichern, geht der Zugriff jetzt gebündelt hier
    durch.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with _db_lock:
            return self._conn.execute(*args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with _db_lock:
            return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        with _db_lock:
            return self._conn.executescript(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _connect() -> sqlite3.Connection:
    """Lazily-opened singleton connection.

    ``check_same_thread=False`` is required because the RPC layer dispatches
    requests on the main thread but spawns worker threads (e.g. the import
    pipeline) that hit the DB on hand-offs. Zugriffe laufen über
    ``_SerialisierteVerbindung``, damit Transaktionen sich nicht überlappen.
    """
    global _conn
    if _conn is not None:
        return _conn
    roh = sqlite3.connect(
        str(db_path()),
        isolation_level=None,  # autocommit off via explicit BEGIN
        check_same_thread=False,
    )
    roh.row_factory = sqlite3.Row
    roh.execute("PRAGMA foreign_keys = ON;")
    _migrate(roh)
    _conn = _SerialisierteVerbindung(roh)  # type: ignore[assignment]
    return _conn


def connection() -> sqlite3.Connection:
    """Die offene Verbindung — für Module, die eigene Tabellen bewirtschaften
    (``sidecar/jobs.py``). Schema und Migrationen bleiben hier."""
    return _connect()


def schema_version() -> int:
    """Aktuelle Schema-Version der geöffneten DB — für Diagnose/Tests."""
    return int(_connect().execute("PRAGMA user_version;").fetchone()[0])


def close() -> None:
    """Close the connection. Called on shutdown; tests also use this.

    Unter ``_db_lock``: schließt man die Verbindung, während ein anderer
    Thread gerade darauf arbeitet, stirbt der Prozess an einer Access
    Violation aus dem SQLite-C-Code — kein Python-Fehler, kein Traceback.
    Beim Beenden ist genau das erreichbar, solange der Job-Worker noch läuft.
    """
    global _conn
    with _db_lock:
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
    """Newest first. Returns MeetingListItem dicts (no speakers/turns).

    ``created_at`` hat nur Sekunden-Auflösung, deshalb der zweite
    Sortierschlüssel: bei einem Stapel-Import fallen viele Meetings in
    dieselbe Sekunde, und `ORDER BY created_at` allein liefert sie dann in
    beliebiger Reihenfolge. ``rowid`` ist die Einfügereihenfolge und macht
    die Sortierung eindeutig.
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT id, title, duration_ms, created_at, status "
        "FROM meetings ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
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
        # text_clean_mode MUSS mit raus: `cleanup.run` entscheidet daran, ob
        # ein Turn in dieser Stufe schon bereinigt ist. Fehlt die Spalte hier,
        # ist die Bedingung immer falsch und jeder Lauf rechnet alles neu.
        "SELECT id, speaker_id, idx, start_ms, end_ms, text_raw, text_clean, "
        "text_clean_mode, words_json, overlap_flag "
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

    Die Statistiken werden **hier** neu berechnet. Vorher stand hier, das sei
    Sache des Aufrufers — nur tat es keiner: nach jedem Zusammenführen zeigten
    Oberfläche und Markdown-Export die alten Anteile, und ihre Summe ergab
    nicht mehr 100 %.
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
        _recompute_speaker_stats(conn, meeting_id)
    return moved


def _recompute_speaker_stats(conn: sqlite3.Connection, meeting_id: str) -> None:
    """Wortzahl, Redezeit und Anteil je Sprecher aus den Turns ableiten.

    Läuft innerhalb einer bestehenden Transaktion. Die Wortzahl kommt aus dem
    Rohtext (nicht aus ``words_json``): der Merger zählt genauso, und der
    Rohtext ist auch dann da, wenn keine Wort-Zeitstempel vorliegen.
    """
    zeilen = conn.execute(
        "SELECT speaker_id, text_raw, start_ms, end_ms FROM turns "
        "WHERE meeting_id = ? AND speaker_id IS NOT NULL",
        (meeting_id,),
    ).fetchall()

    woerter: dict[str, int] = {}
    dauer: dict[str, int] = {}
    for z in zeilen:
        sid = z["speaker_id"]
        woerter[sid] = woerter.get(sid, 0) + len((z["text_raw"] or "").split())
        dauer[sid] = dauer.get(sid, 0) + max(0, int(z["end_ms"]) - int(z["start_ms"]))

    gesamt = sum(dauer.values())
    for sid in {r["speaker_id"] for r in zeilen}:
        anteil = round(100.0 * dauer.get(sid, 0) / gesamt, 1) if gesamt else 0.0
        conn.execute(
            "UPDATE speakers SET word_count = ?, duration_ms = ?, share_pct = ? "
            "WHERE id = ? AND meeting_id = ?",
            (woerter.get(sid, 0), dauer.get(sid, 0), anteil, sid, meeting_id),
        )


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


def set_turn_clean(turn_id: str, text_clean: str, mode: str | None = None) -> bool:
    conn = _connect()
    cur = conn.execute(
        "UPDATE turns SET text_clean = ?, text_clean_mode = ? WHERE id = ?",
        (text_clean, mode, turn_id),
    )
    return cur.rowcount > 0


# --- Einstellungen ---------------------------------------------------------
#
# Schlüssel/Wert in der DB. Der HF-Token bleibt bewusst im
# Windows-Credential-Manager — Geheimnisse und Einstellungen trennen.


def get_setting(key: str, default: str = "") -> str:
    row = _connect().execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row is not None else default


def set_setting(key: str, value: str) -> None:
    _connect().execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# --- Transactions ----------------------------------------------------------


class _TxnCtx:
    """Explizite Transaktion — hält dabei die DB-Sperre.

    Ohne die Sperre war das hier ein doppelter Fehler: zwei gleichzeitige
    Transaktionen ergaben „cannot start a transaction within a transaction",
    und ein Schreibzugriff aus einem anderen Thread landete mitten in dieser
    Transaktion und wurde von einem ROLLBACK **stillschweigend** mitgerissen.
    Transaktionen gelten in SQLite pro Verbindung, und wir haben genau eine.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        _db_lock.acquire()
        try:
            self.conn.execute("BEGIN")
        except BaseException:
            _db_lock.release()
            raise
        return self.conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc_type is None:
                self.conn.execute("COMMIT")
            else:
                self.conn.execute("ROLLBACK")
        finally:
            _db_lock.release()


def _transaction(conn: sqlite3.Connection) -> _TxnCtx:
    return _TxnCtx(conn)
