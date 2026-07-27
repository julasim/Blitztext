"""LLM-Cleanup gegen ein lokales Ollama.

Nur mit ``--ollama``. Der Aufruf ist **asynchron**: ``cleanup.run`` liefert
sofort ``{ok, started, total}`` und arbeitet in einem Worker-Thread weiter —
das Ergebnis kommt über ``cleanup.done``. Der alte Smoke-Test prüfte noch
``result["processed"]`` aus der synchronen Fassung und wäre seit der
Umstellung durchgefallen; deshalb warten wir hier auf das Event.

Portiert aus sidecar/_smoke_cleanup.py und _smoke_e2e.py.
"""

from __future__ import annotations

import threading

import pytest

import sidecar.methods  # noqa: F401 — registriert die @method-Handler
from sidecar.rpc import call_method

pytestmark = pytest.mark.ollama


@pytest.fixture
def events(monkeypatch):
    """Fängt die Sidecar-Events ab, statt sie nach stdout zu schreiben."""
    captured: list[tuple[str, dict]] = []
    done = threading.Event()

    def _capture(name: str, payload: dict | None = None) -> None:
        captured.append((name, payload or {}))
        if name in ("cleanup.done", "cleanup.error"):
            done.set()

    monkeypatch.setattr(sidecar.methods, "emit_event", _capture)
    return captured, done


def test_cleanup_entfernt_fuellwoerter(store, events, tmp_path):
    captured, done = events
    from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict

    words = [
        {"t0_ms": i * 500, "t1_ms": (i + 1) * 500, "text": w}
        for i, w in enumerate(
            "Also ähm ich ich dachte wir machen die Baueingabe im Mai".split()
        )
    ]
    turns, speakers = merge(words, [{"start_ms": 0, "end_ms": 6000, "speaker": "S0"}])

    mid = store.create_meeting(title="Jour fixe", language="de", status="ready")
    store.upsert_speakers(mid, [speaker_to_store_dict(s) for s in speakers])
    persisted = store.get_meeting(mid)
    assert persisted is not None
    label_to_id = {s["label"]: s["id"] for s in persisted["speakers"]}
    store.upsert_turns(mid, [turn_to_store_dict(t, label_to_id) for t in turns])

    res = call_method("cleanup.run", {"meeting_id": mid})
    assert res["started"] is True
    assert res["total"] == len(turns)

    assert done.wait(timeout=180), "cleanup.done kam nicht innerhalb von 3 Minuten"

    m = store.get_meeting(mid)
    assert m is not None
    clean = m["turns"][0]["text_clean"]
    assert clean, "text_clean wurde nicht geschrieben"
    assert "ähm" not in clean.lower()
    assert "Baueingabe" in clean, "Fachbegriff darf nicht verändert werden"


def test_cleanup_ueberspringt_bereits_bereinigte_turns(store, sample_meeting, events):
    """Idempotenz — ein zweiter Lauf darf nicht erneut durch das LLM gehen."""
    captured, done = events
    m = store.get_meeting(sample_meeting)
    assert m is not None
    for t in m["turns"]:
        store.set_turn_clean(t["id"], t["text_raw"])

    call_method("cleanup.run", {"meeting_id": sample_meeting})
    assert done.wait(timeout=60)

    payload = next(p for name, p in captured if name == "cleanup.done")
    assert payload["processed"] == 0
    assert payload["skipped"] == len(m["turns"])


def test_cleanup_unbekanntes_meeting(store):
    from sidecar.rpc import RpcError

    with pytest.raises(RpcError) as exc:
        call_method("cleanup.run", {"meeting_id": "gibt-es-nicht"})

    assert exc.value.code == -32002


def test_lesbar_setzt_satzzeichen(store, events, tmp_path):
    """Stufe B darf interpunktieren — genau der Unterschied zu Stufe A."""
    from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict

    roh = "also ähm der fluchtweg der führt über den osthof das passt so"
    words = [
        {"t0_ms": i * 400, "t1_ms": (i + 1) * 400, "text": w}
        for i, w in enumerate(roh.split())
    ]
    turns, speakers = merge(words, [{"start_ms": 0, "end_ms": 9000, "speaker": "S0"}])

    mid = store.create_meeting(title="Statik", language="de", status="ready")
    store.upsert_speakers(mid, [speaker_to_store_dict(s) for s in speakers])
    persisted = store.get_meeting(mid)
    assert persisted is not None
    label_to_id = {s["label"]: s["id"] for s in persisted["speakers"]}
    store.upsert_turns(mid, [turn_to_store_dict(t, label_to_id) for t in turns])

    captured, done = events
    res = call_method("cleanup.run", {"meeting_id": mid, "mode": "readable"})
    assert res["mode"] == "readable"
    assert done.wait(timeout=180), "cleanup.done kam nicht"

    m = store.get_meeting(mid)
    assert m is not None
    clean = m["turns"][0]["text_clean"]
    assert clean, "text_clean wurde nicht geschrieben"
    assert clean.rstrip()[-1] in ".!?", f"kein Satzende: {clean!r}"
    assert "ähm" not in clean.lower()
    assert "Osthof" in clean or "osthof" in clean, "Inhalt muss erhalten bleiben"


def test_stufenwechsel_rechnet_neu(store, sample_meeting, events):
    """Ohne text_clean_mode würde der zweite Lauf alles überspringen und
    der Umschalter wäre wirkungslos."""
    captured, done = events
    m = store.get_meeting(sample_meeting)
    assert m is not None
    for t in m["turns"]:
        store.set_turn_clean(t["id"], t["text_raw"], mode="faithful")

    call_method("cleanup.run", {"meeting_id": sample_meeting, "mode": "readable"})
    assert done.wait(timeout=180)

    payload = next(p for name, p in captured if name == "cleanup.done")
    assert payload["skipped"] == 0, "andere Stufe darf nicht übersprungen werden"
    assert payload["processed"] > 0


def test_unbekannte_stufe_wird_abgelehnt(store, sample_meeting):
    from sidecar.rpc import RpcError

    with pytest.raises(RpcError) as exc:
        call_method(
            "cleanup.run", {"meeting_id": sample_meeting, "mode": "erfindet-alles"}
        )

    assert exc.value.code == -32602
