"""RPC method implementations — import this to register handlers.

Kept separate from ``sidecar/rpc.py`` so the transport layer stays clean
and the methods can grow independently. Importing this module triggers
all ``@method`` decorators as import-side-effects.
"""

from __future__ import annotations

from pathlib import Path

import httpx

import threading

from core.llm import cleanup_turn
from sidecar import meeting_store
from sidecar.rpc import (
    APP_DEPENDENCY_MISSING,
    APP_NOT_FOUND,
    APP_PIPELINE_FAILED,
    INVALID_PARAMS,
    RpcError,
    emit_event,
    method,
)


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
    from core.llm import OLLAMA_LOCAL_DEFAULT_MODEL
    from sidecar.audio_io import AUDIO_EXTENSIONS
    from sidecar.meeting_pipeline import pick_default_whisper_model

    cuda = _cuda_available()
    return {
        "appdata": str(meeting_store.appdata_dir()),
        "models_dir": str(meeting_store.appdata_dir() / "models"),
        "meetings_dir": str(meeting_store.meetings_dir()),
        "db_path": str(meeting_store.db_path()),
        "cuda_available": cuda,
        "ollama_available": _ollama_available(),
        # Die tatsächlich gewählten Vorgaben. Die Einstellungsseite zeigte
        # vorher den ersten Eintrag aus `models` bzw. eine fest verdrahtete
        # Zeichenkette — auf einem Rechner ohne GPU stand dort large-v3,
        # während wirklich medium lief.
        "whisper_default": pick_default_whisper_model(),
        "cleanup_model": OLLAMA_LOCAL_DEFAULT_MODEL,
        # Für die Modellwahl im Import. `id` geht als whisper_model durch
        # die Queue; der Engine-Dispatch sitzt in meeting_pipeline.
        "models": [
            {
                "id": "large-v3",
                "label": "Whisper large-v3",
                "hint": "höchste Genauigkeit" + ("" if cuda else " — ohne GPU langsam"),
            },
            {
                "id": "large-v3-turbo",
                "label": "Whisper turbo",
                "hint": "fast so genau, deutlich schneller",
            },
            {
                "id": "parakeet-tdt-0.6b-v3",
                "label": "Parakeet v3",
                "hint": "am schnellsten (CPU), 25 europäische Sprachen, erkennt Sprache selbst",
            },
            {
                "id": "medium",
                "label": "Whisper medium",
                "hint": "Kompromiss für Rechner ohne GPU",
            },
        ],
        # Eine Wahrheit für Dateidialog, Drag&Drop und Ordner-Import.
        "audio_extensions": list(AUDIO_EXTENSIONS),
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


# --- Fachvokabular ---------------------------------------------------------
#
# `meeting.import_file` ist am 2026-08-05 entfallen: ein zweiter Einreih-Weg
# neben `queue.enqueue`, ohne Aufrufer — und ohne `hotwords`. Wer ihn benutzt
# hätte, hätte das Firmenvokabular still verloren. Einreihen geht jetzt
# ausschließlich über `queue.enqueue`, das auch Ordner auflöst.


#: Schlüssel der Firmen-Wortliste in der settings-Tabelle.
VOCABULARY_KEY = "vocabulary"

#: Meetings, für die gerade ein Cleanup-Worker läuft (siehe `cleanup.run`).
_cleanup_laeuft: set[str] = set()
_cleanup_lock = threading.Lock()


@method("settings.get_vocabulary")
def settings_get_vocabulary() -> dict:
    """Dauerhafte Firmen-Wortliste (Normen, wiederkehrende Namen)."""
    meeting_store.init_db()
    return {"vocabulary": meeting_store.get_setting(VOCABULARY_KEY)}


@method("settings.set_vocabulary")
def settings_set_vocabulary(vocabulary: str = "") -> dict:
    meeting_store.init_db()
    meeting_store.set_setting(VOCABULARY_KEY, vocabulary or "")
    return {"ok": True}


@method("settings.vocabulary_suggestion")
def settings_vocabulary_suggestion() -> dict:
    """Vorschlagsliste Bauwesen — das Frontend trägt sie ins Feld ein.

    Bewusst **nicht** automatisch gespeichert: Die Liste landet zum Ansehen
    und Kürzen im Feld, gespeichert wird erst auf Knopfdruck. So bleibt
    sichtbar, was das Modell zu hören erwartet.
    """
    from sidecar.vokabular_bau import KERN, kern_als_text

    return {"vocabulary": kern_als_text(), "count": len(KERN)}


@method("queue.enqueue")
def queue_enqueue(
    paths: list[str],
    language: str = "de",
    whisper_model: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    vocabulary: str | None = None,
) -> dict:
    """Mehrere Dateien und/oder **Ordner** einreihen.

    Ordner werden rekursiv aufgelöst und alphabetisch eingereiht. Was nicht
    verarbeitet werden kann, kommt als ``skipped`` mit Begründung zurück —
    bei 50 Dateien will man wissen, welche fehlt und warum.

    Eingereiht wird seriell, ein Job nach
    dem anderen, Fortschritt über Events.
    """
    import logging

    from sidecar.audio_io import build_hotwords, expand_paths
    from sidecar.jobs import JobQueue

    log = logging.getLogger("sidecar.import")
    if isinstance(paths, str):  # Bequemlichkeit für Handaufrufe
        paths = [paths]

    files, skipped = expand_paths(paths)
    log.info("queue.enqueue: %d Pfad(e) → %d Datei(en), %d übersprungen",
             len(paths), len(files), len(skipped))

    # Projektvokabular zuerst — bei der Längenkürzung überlebt, was vorne
    # steht, und das Projektspezifische ist dringlicher als die Firmenliste.
    meeting_store.init_db()
    hotwords, dropped = build_hotwords(
        vocabulary, meeting_store.get_setting(VOCABULARY_KEY)
    )
    if dropped:
        log.warning("Vokabular gekürzt, weggefallen: %s", ", ".join(dropped))

    queue = JobQueue.instance()
    # Läuft der Worker? Scheitert sein Start beim Hochfahren des Sidecars,
    # wird das dort nur geloggt — die Warteschlange nähme danach weiter Jobs
    # an, die niemand abarbeitet, und alles bliebe stumm auf `queued` stehen.
    if not queue.state().get("worker_alive"):
        log.warning("Job-Worker lief nicht — starte ihn nach")
        queue.start()
        if not queue.state().get("worker_alive"):
            raise RpcError(
                APP_PIPELINE_FAILED,
                "Die Warteschlange läuft nicht und ließ sich nicht starten. "
                "Bitte Blitztext neu starten; Details in sidecar.log.",
            )

    enqueued: list[dict] = []
    for f in files:
        try:
            res = queue.enqueue(
                str(f),
                language=language,
                whisper_model=whisper_model,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                hotwords=hotwords or None,
            )
        except Exception as e:  # noqa: BLE001 — eine Datei darf den Stapel nicht killen
            log.exception("queue.enqueue: %s konnte nicht eingereiht werden", f)
            skipped.append({"path": str(f), "reason": str(e)})
            continue
        enqueued.append({**res, "path": str(f)})

    return {
        "enqueued": enqueued,
        "skipped": skipped,
        "count": len(enqueued),
        # Nicht verschweigen, was der Längengrenze zum Opfer fiel.
        "vocabulary_dropped": dropped,
    }


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
def cleanup_run(
    meeting_id: str, model: str | None = None, mode: str = "faithful"
) -> dict:
    """Startet den LLM-Cleanup über alle Turns eines Meetings.

    Asynchron — RPC kehrt sofort zurück, Worker-Thread läuft die Turns
    durch und emittiert ``cleanup.progress`` / ``cleanup.done`` /
    ``cleanup.error`` Events.

    ``mode`` wählt die Stufe: ``"faithful"`` (Default, nur Füllwörter und
    Stotterer) oder ``"readable"`` (zusätzlich Satzzeichen und
    Satzvervollständigung).

    Idempotent **je Stufe**: ein Turn wird übersprungen, wenn er bereits
    in *dieser* Stufe bereinigt wurde. Ein Stufenwechsel rechnet also neu
    — sonst bliebe der Umschalter wirkungslos.

    Returns ``{ok, started, total, mode}``.
    """
    import logging

    from core.llm import CLEANUP_MODES

    log = logging.getLogger("sidecar.cleanup")

    if mode not in CLEANUP_MODES:
        raise RpcError(
            INVALID_PARAMS,
            f"Unbekannte Cleanup-Stufe {mode!r}. "
            f"Erlaubt: {', '.join(sorted(CLEANUP_MODES))}",
        )

    # Vorab prüfen statt jeden Absatz einzeln auflaufen zu lassen: ohne
    # laufendes Ollama scheitern sonst alle Absätze nacheinander, jeder mit
    # einer technischen Meldung, und der Lauf endet nach Minuten ergebnislos.
    if not _ollama_available():
        raise RpcError(
            APP_DEPENDENCY_MISSING,
            "Ollama ist nicht erreichbar (127.0.0.1:11434). Der Cleanup "
            "braucht ein lokal laufendes Ollama mit geladenem Modell.",
        )

    meeting_store.init_db()
    m = meeting_store.get_meeting(meeting_id)
    if m is None:
        raise RpcError(APP_NOT_FOUND, f"meeting {meeting_id} not found")

    total = len(m["turns"])
    log.info("cleanup.run start: meeting=%s turns=%d", meeting_id, total)

    def _worker() -> None:
        try:
            _cleanup_arbeiten(meeting_id, model, mode, log)
        finally:
            # Immer freigeben — sonst bliebe das Meeting nach einem Fehler
            # dauerhaft für weitere Läufe gesperrt.
            with _cleanup_lock:
                _cleanup_laeuft.discard(meeting_id)

    # Kein zweiter Worker auf denselben Turns: zwei Läufe würden dieselben
    # Absätze parallel durchs LLM schicken und sich gegenseitig überschreiben.
    # Das Frontend blockt den Doppelklick inzwischen, aber die CLI und ein
    # späterer Aufrufer tun das nicht — der Schutz gehört hierher.
    with _cleanup_lock:
        if meeting_id in _cleanup_laeuft:
            raise RpcError(
                INVALID_PARAMS,
                "Für dieses Meeting läuft bereits ein Cleanup.",
            )
        _cleanup_laeuft.add(meeting_id)

    threading.Thread(
        target=_worker, name=f"cleanup-{meeting_id[:8]}", daemon=True
    ).start()

    return {"ok": True, "started": True, "total": total, "mode": mode}


def _cleanup_arbeiten(meeting_id: str, model: str | None, mode: str, log) -> None:
    """Der eigentliche Cleanup-Durchlauf — ein LLM-Aufruf je Absatz."""
    # Re-fetch turns inside the worker so we work with fresh state.
    meeting_store.init_db()
    m_fresh = meeting_store.get_meeting(meeting_id)
    if m_fresh is None:
        # fatal: der Lauf endet hier. Die UI darf ihre Fortschrittsanzeige
        # nur in diesem Fall beenden — der Turn-Fehler weiter unten ist
        # ausdrücklich KEIN Abbruch.
        emit_event(
            "cleanup.error",
            {
                "meeting_id": meeting_id,
                "message": "meeting disappeared",
                "fatal": True,
            },
        )
        return
    turns = m_fresh["turns"]
    n = len(turns)
    processed = 0
    skipped = 0

    for i, t in enumerate(turns):
        # Nur überspringen, wenn dieselbe Stufe schon gelaufen ist.
        if t.get("text_clean") and t.get("text_clean_mode") == mode:
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
                mode=mode,
            )
        except Exception as e:
            log.warning("cleanup turn %s failed: %s", t["id"][:8], e)
            emit_event(
                "cleanup.error",
                {
                    "meeting_id": meeting_id,
                    "turn_id": t["id"],
                    "message": str(e),
                    # Nicht fatal: der Worker macht mit dem nächsten
                    # Absatz weiter. Ohne diese Unterscheidung beendete
                    # die UI ihre Anzeige beim ersten Aussetzer und gab
                    # den Knopf frei, während der Lauf noch lief.
                    "fatal": False,
                },
            )
            # Don't break — keep going on subsequent turns.
            continue

        meeting_store.set_turn_clean(t["id"], cleaned, mode=mode)
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


# --- Sachprotokoll ---------------------------------------------------------
#
# Bewusst als Datei im Meeting-Ordner statt in der DB: eine Migration ist
# forward-only, und dieses Feature muss sich erst im Alltag bewähren. Der
# Ordner liegt ohnehin neben der Audiodatei und wird beim Löschen des
# Meetings mit entfernt.

#: Meetings, für die gerade ein Protokoll erzeugt wird.
_protokoll_laeuft: set[str] = set()
_protokoll_lock = threading.Lock()


def _protokoll_pfad(meeting_id: str) -> Path:
    return meeting_store.meeting_folder(meeting_id) / "protokoll.md"


@method("protocol.get")
def protocol_get(meeting_id: str) -> dict:
    """Das gespeicherte Protokoll, falls vorhanden."""
    pfad = _protokoll_pfad(meeting_id)
    if not pfad.exists():
        return {"exists": False, "markdown": ""}
    return {"exists": True, "markdown": pfad.read_text(encoding="utf-8")}


@method("protocol.generate")
def protocol_generate(meeting_id: str, model: str | None = None) -> dict:
    """Sachprotokoll aus dem Transkript erzeugen — **asynchron**.

    Anders als ``cleanup.run`` (das Absatz für Absatz glättet) verdichtet
    dieser Lauf: was besprochen wurde, worauf hingewiesen wurde, was
    entschieden wurde. Ergebnis über ``protocol.done``; der Fortschritt
    kommt als ``protocol.progress``, weil eine Stunde Audio mehrere Minuten
    braucht.
    """
    import logging

    log = logging.getLogger("sidecar.protocol")

    if not _ollama_available():
        raise RpcError(
            APP_DEPENDENCY_MISSING,
            "Ollama ist nicht erreichbar (127.0.0.1:11434). Das Protokoll "
            "braucht ein lokal laufendes Ollama mit geladenem Modell.",
        )

    meeting_store.init_db()
    m = meeting_store.get_meeting(meeting_id)
    if m is None:
        raise RpcError(APP_NOT_FOUND, f"meeting {meeting_id} not found")
    if not m["turns"]:
        raise RpcError(
            INVALID_PARAMS, "Das Meeting hat kein Transkript, aus dem sich ein "
            "Protokoll erzeugen ließe."
        )

    def _worker() -> None:
        from sidecar.protocol import erzeuge_protokoll

        try:
            def melde(fertig: int, gesamt: int) -> None:
                emit_event(
                    "protocol.progress",
                    {"meeting_id": meeting_id, "done": fertig, "total": gesamt},
                )

            ergebnis = erzeuge_protokoll(m, model=model, on_progress=melde)
            _protokoll_pfad(meeting_id).write_text(
                ergebnis["protokoll"], encoding="utf-8"
            )
            log.info(
                "protocol.generate fertig: meeting=%s abschnitte=%d",
                meeting_id, ergebnis["abschnitte"],
            )
            emit_event(
                "protocol.done",
                {
                    "meeting_id": meeting_id,
                    "sections": ergebnis["abschnitte"],
                    "skipped": ergebnis["uebersprungen"],
                },
            )
        except Exception as e:  # noqa: BLE001 — der Worker darf nicht platzen
            log.exception("protocol.generate fehlgeschlagen")
            emit_event(
                "protocol.error", {"meeting_id": meeting_id, "message": str(e)}
            )
        finally:
            with _protokoll_lock:
                _protokoll_laeuft.discard(meeting_id)

    with _protokoll_lock:
        if meeting_id in _protokoll_laeuft:
            raise RpcError(
                INVALID_PARAMS, "Für dieses Meeting läuft bereits eine "
                "Protokoll-Erzeugung."
            )
        _protokoll_laeuft.add(meeting_id)

    threading.Thread(
        target=_worker, name=f"protocol-{meeting_id[:8]}", daemon=True
    ).start()
    return {"ok": True, "started": True, "turns": len(m["turns"])}


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

    speicher_fehler = ""
    try:
        tok = keyring.get_password("Blitztext", "hf_token") or ""
    except Exception as e:  # noqa: BLE001 — Anmeldeinformationsverwaltung gestört
        # Nicht als „kein Token" ausgeben: ist der Credential-Manager gestört,
        # sagt die Oberfläche sonst „nichts gespeichert", obwohl der Token da
        # ist — und der Nutzer trägt ihn ein zweites Mal ein.
        tok = ""
        speicher_fehler = f"{type(e).__name__}: {e}"

    last4 = tok[-4:] if tok else ""
    return {
        "hf_token_present": bool(tok),
        "hf_token_hint": f"hf_…{last4}" if tok else "",
        # Leer, solange alles in Ordnung ist.
        "credential_store_error": speicher_fehler,
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

    Probt **beide** Diarization-Repos (3.1 und community-1) getrennt.
    Grund: community-1 ist eigenständig gated — wer nur die alten
    Bedingungen akzeptiert hat, sieht sonst einen grünen Check, während
    der Import unter pyannote 4 still auf einen Sprecher degradiert.
    Das ``repos``-Feld sagt der UI, welches Modell zugänglich ist; für
    ``ok`` zählt das Repo der **installierten** pyannote-Version.
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

    from sidecar.diarization import diar_model_name

    probed = {}
    for repo_id in (
        "pyannote/speaker-diarization-3.1",
        "pyannote/speaker-diarization-community-1",
    ):
        try:
            hf_hub_download(repo_id=repo_id, filename="config.yaml", token=tok)
            probed[repo_id] = True
        except Exception:
            probed[repo_id] = False

    active_model = diar_model_name()
    active_ok = probed.get(active_model, False)

    if not active_ok:
        return {
            "ok": False,
            "stage": "gated",
            "user": user_name,
            "repos": probed,
            "message": (
                f"Token authentifiziert, aber kein Zugriff auf '{active_model}' — "
                f"das Modell der installierten pyannote-Version. Auf "
                f"huggingface.co die Bedingungen dieses Repos akzeptieren und "
                f"beim Token 'Read access to public gated repos' aktivieren."
            ),
        }

    return {
        "ok": True,
        "stage": "ready",
        "user": user_name,
        "repos": probed,
        "message": f"Eingeloggt als {user_name}, Zugriff auf {active_model} bestätigt.",
    }
