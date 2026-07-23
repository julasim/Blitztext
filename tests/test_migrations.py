"""Migrationen: `PRAGMA user_version` als Zähler, forward-only.

Vorher wurde die Version nur gestempelt, nie gelesen — es gab also gar
keinen Migrationsweg. Diese Tests halten den Mechanismus fest, bevor die
Job-Queue die erste echte zweite Migration mitbringt.
"""

from __future__ import annotations

import sqlite3


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
