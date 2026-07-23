"""Markdown-Export — bisher ungetestet, obwohl es das Endprodukt ist.

Geht bewusst über ``call_method`` statt direkt an die Funktion: damit läuft
derselbe Dispatch-Pfad wie beim Aufruf aus der App.
"""

from __future__ import annotations

from sidecar.rpc import RpcError, call_method
import sidecar.methods  # noqa: F401 — registriert die @method-Handler

import pytest


def test_export_schreibt_datei_mit_transkript(store, sample_meeting, tmp_path):
    out = tmp_path / "protokoll.md"

    res = call_method(
        "export.markdown", {"meeting_id": sample_meeting, "path": str(out)}
    )

    assert res["ok"] is True
    assert out.exists()
    assert res["bytes"] == out.stat().st_size

    text = out.read_text(encoding="utf-8")
    assert "# Test-Meeting" in text
    assert "## Sprecher" in text
    assert "## Transkript" in text
    assert "Guten Morgen" in text
    assert "Passt mir" in text


def test_export_legt_fehlende_ordner_an(store, sample_meeting, tmp_path):
    out = tmp_path / "gibt" / "es" / "noch" / "nicht" / "p.md"

    call_method("export.markdown", {"meeting_id": sample_meeting, "path": str(out)})

    assert out.exists()


def test_export_nutzt_rohtext_wenn_kein_cleanup_vorliegt(
    store, sample_meeting, tmp_path
):
    """use_cleanup=True darf nicht in leere Absätze laufen, solange noch
    kein Turn bereinigt wurde."""
    out = tmp_path / "clean.md"

    call_method(
        "export.markdown",
        {"meeting_id": sample_meeting, "path": str(out), "use_cleanup": True},
    )

    text = out.read_text(encoding="utf-8")
    assert "Guten Morgen" in text


def test_export_bevorzugt_bereinigten_text(store, sample_meeting, tmp_path):
    m = store.get_meeting(sample_meeting)
    assert m is not None
    store.set_turn_clean(m["turns"][0]["id"], "Guten Morgen zusammen.")
    out = tmp_path / "clean2.md"

    call_method(
        "export.markdown",
        {"meeting_id": sample_meeting, "path": str(out), "use_cleanup": True},
    )

    text = out.read_text(encoding="utf-8")
    assert "Guten Morgen zusammen." in text


def test_export_unbekanntes_meeting(store, tmp_path):
    with pytest.raises(RpcError) as exc:
        call_method(
            "export.markdown",
            {"meeting_id": "gibt-es-nicht", "path": str(tmp_path / "x.md")},
        )

    assert exc.value.code == -32002  # APP_NOT_FOUND


def test_zeitstempel_formatierung():
    """00:00:00-Form — fällt sonst erst im fertigen Protokoll auf."""
    from sidecar.methods import _format_timestamp

    assert _format_timestamp(0) == "00:00:00"
    assert _format_timestamp(65_000) == "00:01:05"
    assert _format_timestamp(3_725_000) == "01:02:05"
