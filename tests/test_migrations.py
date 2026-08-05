"""Migrationen: `PRAGMA user_version` als Zähler, forward-only.

Vorher wurde die Version nur gestempelt, nie gelesen — es gab also gar
keinen Migrationsweg. Diese Tests halten den Mechanismus fest, bevor die
Job-Queue die erste echte zweite Migration mitbringt.
"""

from __future__ import annotations

import sqlite3

import pytest


def test_frische_db_landet_auf_aktueller_version(store):
    assert store.schema_version() == store._SCHEMA_VERSION


def test_alle_tabellen_existieren(store):
    conn = store._connect()
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
    }

    assert {"meetings", "speakers", "turns"} <= tables


def test_wiederholtes_oeffnen_migriert_nicht_erneut(store, tmp_path, monkeypatch):
    """Zweiter Start gegen dieselbe Datei darf nichts anfassen — und darf
    vor allem keine Daten verlieren."""
    mid = store.create_meeting(title="Überlebt den Neustart", language="de")
    store.close()

    store.init_db()

    assert store.schema_version() == store._SCHEMA_VERSION
    m = store.get_meeting(mid)
    assert m is not None
    assert m["title"] == "Überlebt den Neustart"


def test_migrationen_sind_lueckenlos_und_aufsteigend():
    """Schützt vor dem klassischen Fehler: zwei Branches vergeben dieselbe
    Nummer, oder eine wird übersprungen."""
    from sidecar import meeting_store

    versions = [v for v, _ in meeting_store._MIGRATIONS]

    assert versions == sorted(versions), "Migrationen müssen aufsteigend stehen"
    assert len(versions) == len(set(versions)), "doppelte Migrationsnummer"
    assert versions == list(range(1, len(versions) + 1)), "Lücke in der Nummerierung"


def test_abgebrochene_migration_wird_zurueckgerollt(tmp_path):
    """Ein Absturz mitten in einem Schritt darf die DB nicht dauerhaft
    unbrauchbar machen.

    Vorher lief jeder Schritt mit ``executescript`` (committet implizit vorab)
    und der Versionsstempel danach als getrennte Anweisung. Starb der Prozess
    dazwischen, blieb ``turns.text_clean_mode`` angelegt, die Version aber auf
    2 — und weil ``ALTER TABLE ADD COLUMN`` kein ``IF NOT EXISTS`` kennt,
    scheiterte **jeder weitere Start** an „duplicate column name". Ohne
    Selbstheilungspfad: die Meeting-Datenbank wäre verloren gewesen.
    """
    from sidecar import meeting_store

    db = tmp_path / "abbruch.db"
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON;")

    # Auf den Stand vor der letzten Migration bringen.
    letzte_nummer, letzte_sql = meeting_store._MIGRATIONS[-1]
    for nummer, sql in meeting_store._MIGRATIONS[:-1]:
        for statement in meeting_store._einzelstatements(sql):
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {nummer};")
    assert conn.execute("PRAGMA user_version;").fetchone()[0] == letzte_nummer - 1

    # Letzten Schritt mit angehängtem Müll scheitern lassen.
    with pytest.raises(sqlite3.Error):
        conn.execute("BEGIN")
        try:
            for statement in meeting_store._einzelstatements(
                letzte_sql + "\nDAS IST KEIN SQL;\n"
            ):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {letzte_nummer};")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    # Nichts darf hängengeblieben sein — auch die Version nicht.
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(turns)")}
    assert "text_clean_mode" not in spalten
    assert conn.execute("PRAGMA user_version;").fetchone()[0] == letzte_nummer - 1

    # Und der nächste Anlauf muss durchgehen.
    assert meeting_store._migrate(conn) == meeting_store._SCHEMA_VERSION
    spalten = {r[1] for r in conn.execute("PRAGMA table_info(turns)")}
    assert "text_clean_mode" in spalten
    conn.close()


def test_pragma_user_version_ist_transaktional():
    """Grundannahme des Rollback-Schutzes oben — ohne sie trüge er nicht."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.execute("BEGIN")
    conn.execute("PRAGMA user_version = 42;")
    conn.execute("ROLLBACK")

    assert conn.execute("PRAGMA user_version;").fetchone()[0] == 0
    conn.close()


def test_migration_laeuft_auf_leerer_datei_an(tmp_path, monkeypatch):
    """Der Weg für alle Bestands-DBs: user_version 0 → Ausgangsschema."""
    from sidecar import meeting_store

    monkeypatch.setenv("APPDATA", str(tmp_path))
    meeting_store.close()

    db = meeting_store.db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(db))
    assert raw.execute("PRAGMA user_version;").fetchone()[0] == 0
    raw.close()

    meeting_store.init_db()

    assert meeting_store.schema_version() == meeting_store._SCHEMA_VERSION
    meeting_store.close()
