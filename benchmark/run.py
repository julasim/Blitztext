"""Messlauf: dieselbe Aufnahme durch die Pipeline, gegen ein korrigiertes
Transkript gerechnet.

Zweck: Änderungen an Modellen oder Stack (Torch-Upgrade, pyannote 4,
anderes ASR-Modell) gegen **eigenes Material** prüfen statt gegen
englische Leaderboard-Durchschnitte.

    # 1. Referenz-Gerüst erzeugen (läuft die Pipeline einmal)
    python benchmark/run.py --prepare benchmark/data/besprechung.mp3

    # 2. benchmark/data/besprechung.reference.md im Editor korrigieren

    # 3. Messen
    python benchmark/run.py --label baseline-large-v3
    python benchmark/run.py --label turbo --model large-v3-turbo
    python benchmark/run.py --label ohne-diarization --no-diarize

    # Ohne vertrauliches Material: Selbsttest über die Windows-Sprachausgabe
    python benchmark/run.py --selftest

Der Lauf benutzt denselben Produktpfad wie die App (``run_import``), aber
mit ``APPDATA`` auf ``benchmark/.work/`` — die echte Meeting-DB wird nicht
angefasst.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCH_DIR.parent
DATA_DIR = BENCH_DIR / "data"
RESULTS_DIR = BENCH_DIR / "results"
WORK_DIR = BENCH_DIR / ".work"

sys.path.insert(0, str(PROJECT_ROOT))

_REAL_APPDATA = os.environ.get("APPDATA")


def _share_model_cache() -> None:
    """Modell-Verzeichnis auf den echten Cache zeigen lassen.

    Mit umgebogenem ``APPDATA`` landen auch die Whisper-Gewichte unter
    ``.work/`` — beim ersten Lauf waren das 2,9 GB Download für ein Modell,
    das die App daneben ohnehin vorhält. Eine Verzeichnis-Junction teilt
    den Cache; sie braucht unter Windows keine Administratorrechte.

    Schlägt es fehl, lädt der Benchmark eben selbst herunter — langsamer,
    aber nicht kaputt.
    """
    if not _REAL_APPDATA:
        return
    real = Path(_REAL_APPDATA) / "Blitztext" / "models"
    link = WORK_DIR / "Blitztext" / "models"
    if link.exists() or not real.exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(real)],
            check=True,
            capture_output=True,
        )
    except Exception:
        pass  # Ohne Junction lädt der Lauf die Modelle selbst.


# APPDATA umbiegen, BEVOR irgendetwas aus sidecar importiert wird —
# meeting_store leitet alle Pfade daraus ab und cached die Verbindung.
WORK_DIR.mkdir(parents=True, exist_ok=True)
_share_model_cache()
os.environ["APPDATA"] = str(WORK_DIR)

from benchmark.metrics import compare_speakers, wer  # noqa: E402
from benchmark.reference import (  # noqa: E402
    load_reference,
    reference_path_for,
)

SELFTEST_TEXT = (
    "Guten Morgen. Wir beginnen die Besprechung mit dem Brandschutz. "
    "Der Fluchtweg soll über den Osthof geführt werden."
)


# --- Umgebung dokumentieren -------------------------------------------------


def environment() -> dict:
    """Versionen in jede Ergebnisdatei. Ohne die weiß in vier Wochen
    niemand mehr, ob eine Messung vor oder nach dem Torch-Upgrade lief."""
    info: dict = {"python": sys.version.split()[0]}
    for name, mod in (("torch", "torch"), ("faster_whisper", "faster_whisper")):
        try:
            info[name] = __import__(mod).__version__
        except Exception:
            info[name] = None
    try:
        from importlib.metadata import version

        info["pyannote.audio"] = version("pyannote.audio")
    except Exception:
        info["pyannote.audio"] = None
    try:
        import torch

        info["cuda"] = bool(torch.cuda.is_available())
        info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        info["cuda"], info["gpu"] = None, None
    info["diarization_device"] = os.environ.get("BLITZTEXT_DIAR_CPU", "1") == "1" and "cpu" or "auto"
    return info


# --- Ein Durchlauf ----------------------------------------------------------


def warm_up(model: str | None, language: str) -> float:
    """Modell laden UND einmal aufrufen, bevor gemessen wird.

    Ohne das zahlt die **erste** Datei jedes Laufs versteckte Einmalkosten
    mit und der Realtime-Faktor wird unbrauchbar — ausgerechnet die Zahl,
    an der man Modelle gegeneinander abwägt. Zwei real erwischte Fälle:
    Whisper lud beim ersten Lauf 3 GB herunter (420 s für 9 s Audio), und
    ONNX optimiert den Graphen beim ersten Inferenz-Aufruf (Parakeet:
    erste Datei 30 s, danach 4 s). Deshalb reicht Laden nicht — eine
    Sekunde Stille durch das Modell schieben gehört dazu.
    """
    import numpy as np

    from sidecar.meeting_pipeline import _get_transcriber, pick_default_whisper_model

    started = time.time()
    t = _get_transcriber(model or pick_default_whisper_model(), language)
    t.transcribe_with_words(np.zeros(16_000, dtype=np.float32))
    return round(time.time() - started, 1)


def transcribe(
    audio: Path,
    *,
    model: str | None,
    language: str,
    diarize: bool,
    hotwords: str | None = None,
) -> dict:
    """Eine Datei durch die volle Pipeline. Gibt Transkript, Sprecher und
    Zeiten zurück."""
    from sidecar import meeting_store
    from sidecar.meeting_pipeline import run_import

    stage_seconds: dict[str, float] = {}
    warnings: list[str] = []

    def on_event(name: str, payload: dict) -> None:
        if name == "meeting.progress" and payload.get("eta_sec") is not None:
            stage_seconds[payload["stage"]] = round(float(payload["eta_sec"]), 2)
        elif name == "meeting.warning":
            warnings.append(f"{payload.get('stage')}: {payload.get('message')}")

    started = time.time()
    meeting_id = run_import(
        str(audio),
        title=audio.stem,
        language=language,
        whisper_model=model,
        on_event=on_event,
        diarize=diarize,
        hotwords=hotwords,
    )
    elapsed = time.time() - started

    meeting_store.init_db()
    m = meeting_store.get_meeting(meeting_id)
    if m is None:
        raise RuntimeError(f"Meeting {meeting_id} verschwunden")

    duration_ms = int(m.get("duration_ms") or 0)
    return {
        "meeting_id": meeting_id,
        "text": " ".join(t["text_raw"] for t in m["turns"]),
        "turns": len(m["turns"]),
        "speakers": len(m["speakers"]),
        "whisper_model": m.get("whisper_model"),
        "language": m.get("language"),
        "duration_ms": duration_ms,
        "elapsed_sec": round(elapsed, 1),
        "realtime_factor": round((duration_ms / 1000) / elapsed, 2) if elapsed > 0 else None,
        "stage_seconds": stage_seconds,
        "warnings": warnings,
    }


def measure(audio: Path, reference_file: Path, run_result: dict) -> dict:
    ref = load_reference(reference_file)
    raw = wer(ref.text, run_result["text"], normalize=False)
    normalized = wer(ref.text, run_result["text"], normalize=True)
    speakers = compare_speakers(ref.speakers, run_result["speakers"])
    return {
        "file": audio.name,
        # Synthetisches Material ist ein Regressionsmelder, kein
        # Qualitätsurteil — das Flag verhindert, dass die Zahlen später
        # als "gemessen auf echten Meetings" gelesen werden.
        "synthetic": "synthetic" in str(audio).lower(),
        "wer": normalized.wer,
        "wer_raw": raw.wer,
        "wer_detail": normalized.as_dict(),
        "speakers": speakers.as_dict(),
        "turns": run_result["turns"],
        "duration_ms": run_result["duration_ms"],
        "elapsed_sec": run_result["elapsed_sec"],
        "realtime_factor": run_result["realtime_factor"],
        "stage_seconds": run_result["stage_seconds"],
        "warnings": run_result["warnings"],
    }


# --- Referenz vorbereiten ---------------------------------------------------


def prepare(audio_paths: list[Path], *, model: str | None, language: str) -> int:
    from sidecar import meeting_store
    from sidecar.methods import _meeting_to_markdown

    for audio in audio_paths:
        target = reference_path_for(audio)
        if target.exists():
            print(f"[übersprungen] {target.name} existiert bereits")
            continue
        print(f"[läuft] {audio.name} …")
        result = transcribe(audio, model=model, language=language, diarize=True)
        m = meeting_store.get_meeting(result["meeting_id"])
        assert m is not None
        target.write_text(_meeting_to_markdown(m, use_cleanup=False), encoding="utf-8")
        print(
            f"[fertig] {target.name} — {result['turns']} Absätze, "
            f"{result['speakers']} Sprecher. Jetzt im Editor korrigieren:"
        )
        print(f"         Text richtigstellen, Sprechernamen vergeben.")
    return 0


# --- Selbsttest -------------------------------------------------------------


def _speak_to_wav(text: str, out: Path) -> None:
    """Windows-Sprachausgabe, deutsche Stimme. Erzeugt bekanntes Material,
    damit der Messaufbau ohne vertrauliche Aufnahmen prüfbar ist."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "try { $s.SelectVoice('Microsoft Katja') } catch { }; "
        f"$s.SetOutputToWaveFile('{out}'); $s.Rate = -1; "
        f"$s.Speak('{text}'); $s.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
    )


def _wav_to_mp3(src: Path, dst: Path) -> None:
    import av

    with av.open(str(src)) as inp, av.open(str(dst), "w") as out:
        ostream = out.add_stream("mp3", rate=44100)
        resampler = av.audio.resampler.AudioResampler(
            format=ostream.format, layout=ostream.layout, rate=ostream.rate
        )
        for frame in inp.decode(inp.streams.audio[0]):
            frame.pts = None
            for rframe in resampler.resample(frame):
                for packet in ostream.encode(rframe):
                    out.mux(packet)
        for packet in ostream.encode(None):
            out.mux(packet)


def selftest(*, model: str | None, language: str) -> int:
    """Voller Durchlauf mit bekanntem Wortlaut. Erwartetes WER nahe null."""
    tmp = WORK_DIR / "selftest"
    tmp.mkdir(parents=True, exist_ok=True)
    wav, mp3 = tmp / "probe.wav", tmp / "probe.mp3"

    print("Erzeuge Sprachprobe über die Windows-Sprachausgabe …")
    try:
        _speak_to_wav(SELFTEST_TEXT, wav)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"FEHLT: Sprachausgabe nicht verfügbar ({e})")
        return 1
    _wav_to_mp3(wav, mp3)
    print(f"MP3: {mp3.stat().st_size} Bytes")

    print("Lade Modell …")
    load_sec = warm_up(model, language)
    print(f"Modell geladen in {load_sec} s")

    result = transcribe(mp3, model=model, language=language, diarize=False)
    score = wer(SELFTEST_TEXT, result["text"])

    print()
    print(f"Referenz:   {SELFTEST_TEXT}")
    print(f"Transkript: {result['text']}")
    print()
    print(f"WER:        {score.wer:.1%}  "
          f"(S={score.substitutions} D={score.deletions} I={score.insertions})")
    print(f"Laufzeit:   {result['elapsed_sec']} s  "
          f"(Realtime-Faktor {result['realtime_factor']})")

    ok = score.wer <= 0.25
    print()
    print("ERGEBNIS:", "OK" if ok else "AUFFÄLLIG — WER über 25 %")
    return 0 if ok else 1


# --- Messlauf ---------------------------------------------------------------


def _summary_markdown(payload: dict) -> str:
    lines = [
        f"# Messlauf {payload['label']}",
        "",
        f"- **Datum:** {payload['timestamp']}",
        f"- **Modell:** {payload['config']['model'] or 'automatisch'}",
        f"- **Sprache:** {payload['config']['language']}",
        f"- **Diarization:** {'an' if payload['config']['diarize'] else 'aus'}",
        f"- **torch:** {payload['environment'].get('torch')} · "
        f"**pyannote.audio:** {payload['environment'].get('pyannote.audio')} · "
        f"**CUDA:** {payload['environment'].get('cuda')}",
        f"- **Modell-Ladezeit:** {payload['environment'].get('model_load_sec')} s "
        f"(vor der Messung, nicht in den Laufzeiten unten enthalten)",
        "",
        "| Datei | WER | roh | Sprecher (erk./echt) | Dauer | RTF |",
        "|---|---:|---:|:---:|---:|---:|",
    ]
    for r in payload["files"]:
        sp = r["speakers"]
        lines.append(
            f"| {r['file']} | {r['wer']:.1%} | {r['wer_raw']:.1%} | "
            f"{sp['hypothesis_count']}/{sp['reference_count']} | "
            f"{r['elapsed_sec']} s | {r['realtime_factor']} |"
        )
    if payload["files"]:
        avg = sum(r["wer"] for r in payload["files"]) / len(payload["files"])
        lines += ["", f"**Mittleres WER: {avg:.1%}** über {len(payload['files'])} Dateien."]
    return "\n".join(lines) + "\n"


def run(
    label: str,
    *,
    model: str | None,
    language: str,
    diarize: bool,
    hotwords: str | None = None,
) -> int:
    from sidecar.audio_io import expand_paths

    if not DATA_DIR.exists():
        print(f"Kein Datenordner: {DATA_DIR}")
        return 1

    files, _skipped = expand_paths([str(DATA_DIR)])
    pairs = [(f, reference_path_for(f)) for f in files]
    pairs = [(a, r) for a, r in pairs if r.exists()]
    if not pairs:
        print(
            f"Keine Referenzen in {DATA_DIR}.\n"
            "Zuerst: python benchmark/run.py --prepare <audio>, dann die "
            "entstandene .reference.md korrigieren."
        )
        return 1

    print("Lade Modell …")
    load_sec = warm_up(model, language)
    print(f"Modell geladen in {load_sec} s — Messung startet jetzt.")

    env = environment()
    env["model_load_sec"] = load_sec
    payload = {
        "label": label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "model": model,
            "language": language,
            "diarize": diarize,
            "hotwords": hotwords,
        },
        "environment": env,
        "files": [],
    }

    for audio, ref in pairs:
        print(f"[läuft] {audio.name} …")
        result = transcribe(
            audio,
            model=model,
            language=language,
            diarize=diarize,
            hotwords=hotwords,
        )
        row = measure(audio, ref, result)
        payload["files"].append(row)
        print(
            f"   WER {row['wer']:.1%} · Sprecher "
            f"{row['speakers']['hypothesis_count']}/{row['speakers']['reference_count']} "
            f"· {row['elapsed_sec']} s"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    base = RESULTS_DIR / f"{stamp}-{label}"
    base.with_suffix(".json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    base.with_suffix(".md").write_text(_summary_markdown(payload), encoding="utf-8")

    print()
    print(_summary_markdown(payload))
    print(f"Geschrieben: {base.with_suffix('.json').name} + .md")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Qualität der Transkription gegen korrigierte Referenzen messen.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--prepare", nargs="+", metavar="AUDIO",
                   help="Referenz-Gerüst erzeugen (Pipeline einmal laufen lassen)")
    p.add_argument("--label", help="Messlauf starten und unter diesem Namen ablegen")
    p.add_argument("--selftest", action="store_true",
                   help="Durchlauf mit synthetischer Sprachprobe, ohne eigenes Material")
    p.add_argument("--model", default=None,
                   help="Whisper-Modell (Default: large-v3 mit CUDA, sonst medium)")
    p.add_argument("--language", default="de")
    p.add_argument("--no-diarize", action="store_true",
                   help="pyannote überspringen — misst, was die Sprechertrennung kostet")
    # nargs="+": PowerShell zerlegt eine kommaseparierte Liste beim Aufruf
    # in Einzelargumente, egal wie man quotet. Statt dagegen anzukämpfen
    # nehmen wir die Teile entgegen und fügen sie wieder zusammen.
    p.add_argument("--hotwords", nargs="+", default=None,
                   help="Fachvokabular, kommasepariert (nur Whisper-Modelle)")
    args = p.parse_args()

    hotwords = " ".join(args.hotwords) if args.hotwords else None

    diarize = not args.no_diarize

    if args.selftest:
        return selftest(model=args.model, language=args.language)
    if args.prepare:
        return prepare([Path(a) for a in args.prepare],
                       model=args.model, language=args.language)
    if args.label:
        return run(
            args.label,
            model=args.model,
            language=args.language,
            diarize=diarize,
            hotwords=hotwords,
        )

    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
