"""Orchestration: audio file → transcript + diarization → turns → DB.

The single entry point is :func:`run_import`. It runs the five stages
sequentially, emits progress notifications to the RPC event stream after
each stage, and returns the final meeting id.

Stages (weighting of overall progress in brackets):

    decode     [5 %]   audio_io.load_audio
    transcribe [55 %]  core.transcription.transcribe_with_words
    diarize    [30 %]  sidecar.diarization.DiarizationPipeline.diarize
    merge      [5 %]   sidecar.merger.merge
    persist    [5 %]   meeting_store writes + normalized WAV copy

On failure at any stage the meeting is left in status=``"error"`` and the
error is re-raised so the caller (the RPC method) can return a
structured JSON-RPC error to the UI.
"""

from __future__ import annotations

import shutil
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from core.transcription import Transcriber
from sidecar import audio_io, meeting_store
from sidecar.diarization import DiarizationPipeline, diar_model_name
from sidecar.merger import merge, speaker_to_store_dict, turn_to_store_dict


class _DiarizationSkipped(Exception):
    """Interner Sprung: ``diarize=False`` nimmt denselben Ausgang wie ein
    Diarization-Fehler — leere Segmentliste, der Merger macht daraus einen
    Sprecher. Kein öffentlicher Fehlerfall, deshalb privat."""


class PipelineCancelled(Exception):
    """Der Lauf wurde abgebrochen — kein Fehler.

    Wird geworfen, sobald ``should_cancel()`` an einem Prüfpunkt True
    liefert. ``run_stages`` behandelt das getrennt von echten Fehlern: das
    Meeting bleibt **nicht** auf ``status="error"`` stehen, und es geht kein
    ``meeting.error``-Event raus.
    """


# --- Progress helpers ------------------------------------------------------

_STAGES = [
    ("decode", 0.05),
    ("transcribe", 0.55),
    ("diarize", 0.30),
    ("merge", 0.05),
    ("persist", 0.05),
]
_STAGE_OFFSETS = {
    name: sum(w for _, w in _STAGES[:i]) for i, (name, _) in enumerate(_STAGES)
}
_STAGE_WIDTH = dict(_STAGES)


def _emit(
    on_event: Callable[[str, dict], None] | None,
    meeting_id: str,
    stage: str,
    stage_pct: float,
    stage_elapsed_sec: float | None = None,
) -> None:
    """Bridge per-stage progress to a unified 0..1 progress value.

    ``stage_elapsed_sec`` ist die **Laufzeit der gerade abgeschlossenen**
    Stufe, keine Restzeit — das Feld hieß bis 2026-08-05 ``eta_sec``, und die
    Oberfläche zeigte den Wert folgerichtig als „noch ~X s" an. Geschätzt
    wird die Restzeit jetzt im Frontend aus Gesamtfortschritt und bisher
    verstrichener Zeit.
    """
    if on_event is None:
        return
    stage_pct = max(0.0, min(1.0, stage_pct))
    total = _STAGE_OFFSETS[stage] + _STAGE_WIDTH[stage] * stage_pct
    on_event(
        "meeting.progress",
        {
            "meeting_id": meeting_id,
            "stage": stage,
            "pct": round(total, 3),
            "stage_elapsed_sec": stage_elapsed_sec,
        },
    )


# --- Model caching ---------------------------------------------------------

# Ein geladenes Whisper-Modell belegt je nach Größe mehrere GB im VRAM.
# Solange die Oberfläche kein Modell zur Wahl stellte, lag hier genau ein
# Eintrag; sobald sie es tut, würden sich large-v3, turbo und medium
# nebeneinander stapeln. Deshalb ein harter Deckel statt eines Caches, der
# nur wächst: Modellwechsel sind selten, ein Neuladen kostet Sekunden, ein
# volles VRAM kostet den Import.
_TRANSCRIBER_CACHE_SIZE = 1

_transcriber_cache: "OrderedDict[str, Transcriber]" = OrderedDict()


def _pick_device_for_whisper() -> tuple[str, str]:
    """Returns (device, compute_type) for faster-whisper.

    Meeting-mode wants CUDA + float16 if available — orders of magnitude
    faster than int8 on CPU for large-v3-turbo. Without GPU we fall back
    to int8 on CPU (compatible with old i7s, no extra memory).
    """
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _release_vram() -> None:
    """Freigegebene Modelle aus dem VRAM räumen. Ohne das bleibt der
    Speicher belegt, bis der Prozess endet — beim Modellwechsel mitten in
    einem Stapel wäre das genau der falsche Moment."""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _get_transcriber(model: str, language: str):
    """Engine-Dispatch über den Modellnamen.

    ``parakeet-tdt-0.6b-v3`` → ONNX-Pfad (CPU, ``core/parakeet.py``),
    alles andere → faster-whisper. Beide Klassen haben dieselbe
    ``transcribe_with_words``-Oberfläche; ab hier ist der Rest der
    Pipeline engine-blind.
    """
    from core.parakeet import MODEL_ID as PARAKEET_ID, ParakeetTranscriber

    is_parakeet = model == PARAKEET_ID
    device, compute_type = ("cpu", "onnx") if is_parakeet else _pick_device_for_whisper()
    key = f"{model}:{language}:{device}"

    cached = _transcriber_cache.get(key)
    if cached is not None:
        _transcriber_cache.move_to_end(key)
        return cached

    if is_parakeet:
        t = ParakeetTranscriber(language=language)
    else:
        t = Transcriber(
            model_size=model,
            language=language,
            device=device,
            compute_type=compute_type,
        )
    t.load()
    _transcriber_cache[key] = t

    while len(_transcriber_cache) > _TRANSCRIBER_CACHE_SIZE:
        _transcriber_cache.popitem(last=False)
        _release_vram()

    return t


def pick_default_whisper_model() -> str:
    """``large-v3`` if CUDA (~10% more accurate than turbo, especially on
    short noisy clips with quiet speakers), ``medium`` else."""
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "large-v3"
    except Exception:
        pass
    return "medium"


# --- Main entry point ------------------------------------------------------


def create_meeting_shell(
    file_path: str,
    *,
    title: str | None = None,
    language: str = "de",
    whisper_model: str | None = None,
) -> tuple[str, str]:
    """Insert an empty meeting row + return (meeting_id, resolved_model).

    Split out from :func:`run_import` so the RPC layer can insert the row
    synchronously (to return an id to the UI) and then fire off the heavy
    stages in a worker thread via :func:`run_stages`.
    """
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"Audio-Datei nicht gefunden: {file_path}")

    if whisper_model is None:
        whisper_model = pick_default_whisper_model()

    meeting_store.init_db()
    meeting_id = meeting_store.create_meeting(
        title=title or src.stem,
        language=language,
        whisper_model=whisper_model,
        diar_model=diar_model_name(),
        status="processing",
    )
    return meeting_id, whisper_model


def run_stages(
    meeting_id: str,
    file_path: str,
    *,
    language: str = "de",
    whisper_model: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    on_event: Callable[[str, dict], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    diarize: bool = True,
    hotwords: str | None = None,
) -> None:
    """Decode → transcribe → diarize → merge → persist for an existing
    meeting row. Does all the heavy lifting.

    ``diarize=False`` überspringt pyannote. Der Merger kommt damit klar —
    er erzeugt dann einen Sprecher und trennt an langen Pausen, denselben
    Weg wie bei einem Diarization-Fehler. Spart rund 30 % der Laufzeit und
    braucht keinen HF-Token; sinnvoll für Vorträge und Sprachnotizen.

    ``should_cancel`` wird an den Stage-Grenzen und nach jedem
    Whisper-Segment abgefragt; liefert es True, fliegt
    :class:`PipelineCancelled`. **Während der Diarization gibt es keinen
    Prüfpunkt** — pyannote meldet dort keinen Fortschritt, der Abbruch
    greift also erst, wenn sie fertig ist.
    """
    src = Path(file_path)

    def _guard() -> None:
        if should_cancel is not None and should_cancel():
            raise PipelineCancelled()

    try:
        # -- Stage: decode --------------------------------------------------
        _guard()
        _emit(on_event, meeting_id, "decode", 0.0)
        t0 = time.time()
        audio, duration_ms = audio_io.load_audio(str(src))
        meeting_store.set_duration(meeting_id, duration_ms)

        # Copy source next to the meeting folder for later replay / speaker
        # preview. We keep the original container, not the resampled WAV —
        # loses less info if the user ever re-exports.
        # Der same-Zweig fängt den Fall ab, dass die Quelle bereits im
        # Meeting-Ordner liegt — das ist der Weg für ein künftiges
        # meeting.reprocess, das gegen die schon kopierte Datei läuft.
        folder = meeting_store.meeting_folder(meeting_id)
        source_copy = folder / f"source{src.suffix.lower()}"
        try:
            same = source_copy.resolve() == src.resolve()
        except Exception:
            same = False
        if not same:
            shutil.copy2(src, source_copy)
            meeting_store.set_audio_path(meeting_id, str(source_copy))
        _emit(on_event, meeting_id, "decode", 1.0, stage_elapsed_sec=time.time() - t0)

        # -- Stage: transcribe ---------------------------------------------
        _guard()
        _emit(on_event, meeting_id, "transcribe", 0.0)
        transcriber = _get_transcriber(whisper_model, language)
        ts_start = time.time()

        def _on_transcribe_progress(p: float) -> None:
            # Läuft einmal je Whisper-Segment. Der einzige feingranulare
            # Abbruchpunkt im ganzen Lauf — und der wichtigste, weil
            # Transkription 55 % der Zeit ausmacht.
            _guard()
            _emit(on_event, meeting_id, "transcribe", p)

        words, info = transcriber.transcribe_with_words(
            audio, on_progress=_on_transcribe_progress, hotwords=hotwords
        )
        detected = info.get("language")
        if detected and detected not in ("auto", language):
            # Auto-detect result differs — store what the engine found.
            # "auto" heißt: die Engine benennt die Sprache nicht (Parakeet),
            # dann bleibt die Nutzer-Angabe stehen.
            meeting_store.set_language(meeting_id, detected)

        _emit(on_event, meeting_id, "transcribe", 1.0, stage_elapsed_sec=time.time() - ts_start)

        # -- Stage: diarize -------------------------------------------------
        # Best-effort: if pyannote can't load (missing HF token, missing
        # license acceptance, no CUDA fallback path …) we proceed with an
        # empty segment list. The merger then produces a single "Speaker 1"
        # turn list, splitting on long pauses for readability. The user
        # gets a usable transcript instead of a hard import failure.
        _guard()
        _emit(on_event, meeting_id, "diarize", 0.0)
        diar_start = time.time()
        segments: list[dict] = []
        try:
            if not diarize:
                raise _DiarizationSkipped()
            pipeline = DiarizationPipeline.instance()
            segments = pipeline.diarize(
                audio,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
                on_progress=lambda p: _emit(
                    on_event, meeting_id, "diarize", p
                ),
            )
        except _DiarizationSkipped:
            pass
        except (RuntimeError, OSError, TypeError, AttributeError, ValueError) as e:
            # „Best effort" muss auch für Fehler gelten, die NICHT als
            # RuntimeError ankommen: fehlende DLLs melden sich als OSError,
            # eine unerwartete Ausgabeform von pyannote als TypeError oder
            # AttributeError. Bisher beendete beides den ganzen Import,
            # statt in den Ein-Sprecher-Fallback zu gehen.
            #
            # Surface as a non-fatal warning so the UI can show a banner.
            if on_event is not None:
                on_event(
                    "meeting.warning",
                    {
                        "meeting_id": meeting_id,
                        "stage": "diarize",
                        "message": str(e),
                        "fallback": "single_speaker",
                    },
                )
        _emit(on_event, meeting_id, "diarize", 1.0, stage_elapsed_sec=time.time() - diar_start)

        # -- Stage: merge ---------------------------------------------------
        _guard()
        _emit(on_event, meeting_id, "merge", 0.0)
        turns, speakers = merge(words, segments)
        _emit(on_event, meeting_id, "merge", 1.0)

        # -- Stage: persist -------------------------------------------------
        _emit(on_event, meeting_id, "persist", 0.0)
        speaker_dicts = [speaker_to_store_dict(s) for s in speakers]
        meeting_store.upsert_speakers(meeting_id, speaker_dicts)
        refreshed = meeting_store.get_meeting(meeting_id)
        assert refreshed is not None
        label_to_id = {s["label"]: s["id"] for s in refreshed["speakers"]}
        turn_dicts = [turn_to_store_dict(t, label_to_id) for t in turns]
        meeting_store.upsert_turns(meeting_id, turn_dicts)
        meeting_store.set_status(meeting_id, "ready")
        _emit(on_event, meeting_id, "persist", 1.0)

        if on_event is not None:
            on_event("meeting.done", {"meeting_id": meeting_id})

    except PipelineCancelled:
        # Kein Fehler: kein status="error", kein meeting.error. Die
        # Warteschlange räumt die Meeting-Hülle auf, sobald sie den
        # Abbruch verbucht hat.
        raise

    except Exception as e:
        meeting_store.set_status(meeting_id, "error")
        if on_event is not None:
            on_event(
                "meeting.error",
                {"meeting_id": meeting_id, "message": str(e)},
            )
        raise


def run_import(
    file_path: str,
    *,
    title: str | None = None,
    language: str = "de",
    whisper_model: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    on_event: Callable[[str, dict], None] | None = None,
    diarize: bool = True,
    hotwords: str | None = None,
) -> str:
    """Convenience: create the shell + run all stages synchronously.

    Benutzt von Tests und vom Benchmark. Die Warteschlange ruft
    ``create_meeting_shell`` + ``run_stages`` getrennt auf, weil sie die
    ``meeting_id`` sofort braucht.
    """
    meeting_id, model = create_meeting_shell(
        file_path, title=title, language=language, whisper_model=whisper_model
    )
    run_stages(
        meeting_id,
        file_path,
        language=language,
        whisper_model=model,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        on_event=on_event,
        diarize=diarize,
        hotwords=hotwords,
    )
    return meeting_id
