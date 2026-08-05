"""Standalone Meeting-Transkription via CLI.

Schickt eine Audiodatei durch die volle Sidecar-Pipeline (Whisper +
Diarization, falls HF-Token vorhanden, sonst Single-Speaker-Fallback)
und schreibt das Ergebnis als Markdown raus. Optional auch direkt
LLM-Cleanup über Ollama.

Beispiele:
    py -3.11 transcribe.py "C:\\path\\to\\meeting.mp3"
    py -3.11 transcribe.py meeting.wav --cleanup --out protokoll.md
    py -3.11 transcribe.py meeting.m4a --max-speakers 4

Output landet (wenn nicht --out gesetzt) neben der Audiodatei als
``<basename>.md``. Ein Eintrag in der Meeting-DB unter %APPDATA%\\Blitztext
wird angelegt — du findest die Aufnahme später auch in der App.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Modulpfad für relative Imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sidecar import meeting_store
from sidecar.meeting_pipeline import run_import


STAGE_LABELS = {
    "decode": "Audio dekodieren",
    "transcribe": "Transkribieren",
    "diarize": "Sprecher erkennen",
    "merge": "Zusammenführen",
    "persist": "Speichern",
}


class ProgressPrinter:
    """Kompakter In-Place-Progress auf stderr — eine Zeile pro Stage."""

    def __init__(self) -> None:
        self.cur_stage: str | None = None
        self.last_pct_int: int = -1
        self.warnings: list[str] = []

    def __call__(self, name: str, payload: dict) -> None:
        if name == "meeting.progress":
            stage = payload.get("stage")
            pct = float(payload.get("pct") or 0)
            pct_int = int(pct * 100)
            if stage != self.cur_stage:
                if self.cur_stage is not None:
                    sys.stderr.write("\n")
                self.cur_stage = stage
                self.last_pct_int = -1
            if pct_int != self.last_pct_int:
                label = STAGE_LABELS.get(stage or "", stage or "?")
                bar = "█" * (pct_int // 5) + "·" * (20 - pct_int // 5)
                sys.stderr.write(f"\r  {label:18} [{bar}] {pct_int:3d}%")
                sys.stderr.flush()
                self.last_pct_int = pct_int
        elif name == "meeting.warning":
            sys.stderr.write(
                f"\n  ⚠ {payload.get('stage', '?')}: {payload.get('message', '')}\n"
            )
            self.warnings.append(payload.get("message", ""))
        elif name == "meeting.done":
            sys.stderr.write("\n")
        elif name == "meeting.error":
            sys.stderr.write(
                f"\n  ✗ Pipeline-Fehler in {payload.get('stage')}: "
                f"{payload.get('message')}\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lokale Audio-Transkription mit Sprecher-Erkennung."
    )
    parser.add_argument("audio", help="Pfad zur Audio-Datei (WAV/MP3/M4A/FLAC/OGG/MP4)")
    parser.add_argument(
        "--title", help="Meeting-Titel (default: Dateiname ohne Endung)"
    )
    parser.add_argument(
        "--language", default="de", help="Sprache (de/en/auto). Default: de"
    )
    parser.add_argument(
        "--whisper-model",
        help="ASR-Modell (default: large-v3 bei CUDA, sonst medium; "
        "parakeet-tdt-0.6b-v3 für den schnellen CPU-Pfad)",
    )
    parser.add_argument(
        "--vocabulary",
        help="Fachvokabular, kommasepariert (nur Whisper-Modelle)",
    )
    parser.add_argument(
        "--min-speakers", type=int, help="Hinweis an pyannote: minimale Sprecherzahl"
    )
    parser.add_argument(
        "--max-speakers", type=int, help="Hinweis an pyannote: maximale Sprecherzahl"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Anschließend LLM-Cleanup (Füllwörter raus) via lokalem Ollama",
    )
    parser.add_argument(
        "--cleanup-model",
        default="qwen2.5:7b-instruct",
        help="Ollama-Modell für Cleanup (default: qwen2.5:7b-instruct)",
    )
    parser.add_argument(
        "--cleanup-mode",
        default="faithful",
        choices=["faithful", "readable"],
        help="faithful: nur Füllwörter raus. readable: zusätzlich "
        "Satzzeichen und angefangene Sätze zu Ende führen",
    )
    parser.add_argument(
        "--out",
        help="Ausgabe-Markdown-Pfad (default: <audio-basename>.md neben der Quelle)",
    )
    args = parser.parse_args()

    src = Path(args.audio).expanduser().resolve()
    if not src.exists():
        print(f"Fehler: Audio-Datei nicht gefunden: {src}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else src.with_suffix(".md")

    print(f"Quelle:   {src}", file=sys.stderr)
    print(f"Ausgabe:  {out_path}", file=sys.stderr)
    print(f"Modell:   {args.whisper_model or '(auto)'}", file=sys.stderr)
    print(f"Sprache:  {args.language}", file=sys.stderr)
    if args.cleanup:
        print(
            f"Cleanup:  via Ollama / {args.cleanup_model} ({args.cleanup_mode})",
            file=sys.stderr,
        )
    print("", file=sys.stderr)

    progress = ProgressPrinter()
    t0 = time.time()
    try:
        meeting_id = run_import(
            str(src),
            title=args.title,
            language=args.language,
            whisper_model=args.whisper_model,
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
            hotwords=args.vocabulary,
            on_event=progress,
        )
    except Exception as e:
        print(f"\nPipeline fehlgeschlagen: {e}", file=sys.stderr)
        return 1
    transcribe_dt = time.time() - t0
    print(f"\nFertig in {transcribe_dt:.1f}s — meeting_id {meeting_id}", file=sys.stderr)

    # Optional LLM cleanup.
    #
    # cleanup.run ist asynchron (Worker-Thread + Events) — für eine CLI, die
    # gleich danach exportiert, wäre das wertlos. Deshalb gehen wir hier
    # direkt über cleanup_turn und warten Turn für Turn ab.
    if args.cleanup:
        from core.llm import cleanup_turn

        print(
            "\nLLM-Cleanup läuft (kann bei langen Meetings einige Minuten dauern)…",
            file=sys.stderr,
        )
        t1 = time.time()
        meeting_store.init_db()
        m = meeting_store.get_meeting(meeting_id)
        turns = m["turns"] if m else []
        done = failed = 0
        for i, t in enumerate(turns):
            prev_text = turns[i - 1]["text_raw"] if i > 0 else None
            next_text = turns[i + 1]["text_raw"] if i + 1 < len(turns) else None
            try:
                cleaned = cleanup_turn(
                    t["text_raw"],
                    prev_text=prev_text,
                    next_text=next_text,
                    model=args.cleanup_model,
                    mode=args.cleanup_mode,
                )
            except Exception as e:
                failed += 1
                if failed == 1:
                    print(f"  Cleanup-Fehler: {e}", file=sys.stderr)
                continue
            meeting_store.set_turn_clean(t["id"], cleaned, mode=args.cleanup_mode)
            done += 1
            print(f"\r  {done}/{len(turns)} Absätze", end="", file=sys.stderr)
        print(
            f"\nCleanup fertig in {time.time() - t1:.1f}s — "
            f"{done} bereinigt, {failed} fehlgeschlagen",
            file=sys.stderr,
        )

    # Markdown export.
    from sidecar.methods import export_markdown

    res = export_markdown(
        meeting_id=meeting_id,
        path=str(out_path),
        use_cleanup=args.cleanup,
    )
    print(f"Markdown geschrieben: {res['path']} ({res['bytes']} Bytes)", file=sys.stderr)

    if progress.warnings:
        print(
            "\nHinweis: Sprechertrennung war nicht aktiv "
            "(siehe Warnungen oben). Der Transkript wurde unter "
            "'Speaker 1' abgelegt, an Pausen in Absätze geteilt. "
            "Wenn du den HF-Token konfigurierst, läuft der nächste "
            "Import mit voller Diarization.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
