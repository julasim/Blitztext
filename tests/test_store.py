"""meeting_store: Persistenz, Sprecher-Operationen, Kaskaden.

Portiert aus sidecar/_smoke_store.py, aufgeteilt in einzelne Fälle — beim
Fehlschlag sieht man dann, *welcher* Schritt gebrochen ist, statt nur den
ersten.
"""

from __future__ import annotations

from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict


def test_round_trip_erhaelt_turns_und_woerter(store, sample_meeting):
    m = store.get_meeting(sample_meeting)

    assert m is not None
    assert m["title"] == "Test-Meeting"
    assert m["status"] == "ready"
    assert len(m["speakers"]) == 2
    assert len(m["turns"]) == 2

    t0, t1 = m["turns"]
    assert t0["idx"] == 0
    assert t0["text_raw"] == "Guten Morgen"
    assert len(t0["words"]) == 2, "words_json muss den Wort-Stream überleben"
    assert t1["text_raw"] == "Passt mir"
    assert t1["speaker_id"] != t0["speaker_id"]


def test_umlaute_ueberleben_die_db(store):
    """SQLite + JSON-Serialisierung der Wörter — beides muss UTF-8 sauber halten."""
    words = [
        {"t0_ms": 0, "t1_ms": 500, "text": "ÖNORM"},
        {"t0_ms": 500, "t1_ms": 1000, "text": "Grundstücksfläche"},
    ]
    turns, speakers = merge(words, [{"start_ms": 0, "end_ms": 1200, "speaker": "S0"}])

    mid = store.create_meeting(title="Prüfstatik", language="de")
    store.upsert_speakers(mid, [speaker_to_store_dict(s) for s in speakers])
    persisted = store.get_meeting(mid)
    assert persisted is not None
    label_to_id = {s["label"]: s["id"] for s in persisted["speakers"]}
    store.upsert_turns(mid, [turn_to_store_dict(t, label_to_id) for t in turns])

    m = store.get_meeting(mid)
    assert m is not None
    assert m["title"] == "Prüfstatik"
    assert m["turns"][0]["text_raw"] == "ÖNORM Grundstücksfläche"
    assert m["turns"][0]["words"][0]["w"] == "ÖNORM"


def test_sprecher_umbenennen(store, sample_meeting):
    m = store.get_meeting(sample_meeting)
    assert m is not None
    speaker_id = m["speakers"][0]["id"]

    assert store.rename_speaker(sample_meeting, speaker_id, "Julius") is True

    m2 = store.get_meeting(sample_meeting)
    assert m2 is not None
    assert m2["speakers"][0]["name"] == "Julius"


def test_sprecher_zusammenfassen(store, sample_meeting):
    m = store.get_meeting(sample_meeting)
    assert m is not None
    target, source = m["speakers"][0]["id"], m["speakers"][1]["id"]

    moved = store.merge_speakers(sample_meeting, source_id=source, target_id=target)

    assert moved == 1
    m2 = store.get_meeting(sample_meeting)
    assert m2 is not None
    assert len(m2["speakers"]) == 1
    assert all(t["speaker_id"] == target for t in m2["turns"])


def test_unbekannter_sprecher_meldet_sich(store, sample_meeting):
    assert store.rename_speaker(sample_meeting, "gibt-es-nicht", "X") is False


def test_loeschen_raeumt_kaskadierend_auf(store, sample_meeting):
    assert store.delete_meeting(sample_meeting) is True

    assert store.get_meeting(sample_meeting) is None
    assert store.list_meetings() == []
    # Foreign Keys mit ON DELETE CASCADE — nur aktiv, wenn das PRAGMA je
    # Verbindung gesetzt wurde. Genau das prüfen wir hier mit.
    conn = store._connect()
    assert conn.execute("SELECT COUNT(*) FROM turns;").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM speakers;").fetchone()[0] == 0


def test_liste_zeigt_neueste_zuerst(store):
    first = store.create_meeting(title="Alt", language="de")
    second = store.create_meeting(title="Neu", language="de")

    listing = store.list_meetings()

    assert [m["id"] for m in listing][:2] == [second, first]


def test_titel_aendern(store, sample_meeting):
    assert store.set_title(sample_meeting, "Umbenannt") is True

    m = store.get_meeting(sample_meeting)
    assert m is not None
    assert m["title"] == "Umbenannt"
