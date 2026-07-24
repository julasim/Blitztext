"""Synthetischer Mehrsprecher-Testsatz aus den Windows-Stimmen.

Erzeugt MP3-Dateien mit **bekanntem** Text, **bekannter** Sprecherzahl und
bekannten Turn-Grenzen — und schreibt die wahre ``.reference.md`` gleich
daneben. Referenz ohne eine Minute Handarbeit.

    python benchmark/make_testset.py

Grenze, die man kennen muss: TTS-Sprache ist sauber — kein Dialekt, keine
Kreuzreden, kein Raumhall, und synthetische Stimmen haben untypische
Sprecher-Embeddings (zwei können für pyannote wie eine klingen). Der
Testsatz ist ein **Regressionsmelder** („ist es schlechter geworden?"),
kein Qualitätsurteil („ist es gut genug?"). Letzteres beantwortet nur
echtes Material.

WICHTIG: Niemals ``run.py --prepare`` auf diese Dateien laufen lassen —
das würde die Pipeline-Ausgabe zur Referenz machen und jede Messung im
Kreis drehen. Die Referenz kommt aus dem Drehbuch, nirgendwo sonst her.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

BENCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCH_DIR.parent
OUT_DIR = BENCH_DIR / "data" / "synthetic"

sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_RATE = 16_000
PAUSE_SEC = 0.8  # unter der 1200-ms-Turn-Grenze des Mergers

# --- Drehbücher -------------------------------------------------------------
#
# (sprecher, satz). Die Sprecher werden Windows-Stimmen zugeordnet, in der
# Reihenfolge, in der sie im Drehbuch auftreten.

SCRIPTS: dict[str, list[tuple[str, str]]] = {
    "wechsel-2": [
        ("Anna", "Guten Morgen, wir beginnen mit dem Brandschutz."),
        ("Bernd", "Einverstanden. Der Fluchtweg soll über den Osthof geführt werden."),
        ("Anna", "Dann brauchen wir eine zweite Tür im Treppenhaus."),
        ("Bernd", "Die Tür muss nach außen aufschlagen, sonst gibt es keine Freigabe."),
        ("Anna", "Gut, ich trage das in den Plan ein und schicke ihn morgen."),
        ("Bernd", "Danke, dann besprechen wir den Rest am Donnerstag."),
    ],
    "runde-4": [
        ("Anna", "Ich eröffne die Besprechung zum Projekt Sophienhof."),
        ("Bernd", "Die Statik ist freigegeben."),
        ("Clara", "Beim Schallschutz fehlt noch das Gutachten."),
        ("David", "Das Gutachten kommt nächste Woche."),
        ("Anna", "Wer übernimmt die Abstimmung mit der Behörde?"),
        ("Clara", "Das mache ich."),
        ("Bernd", "Ich schicke die Pläne heute noch an alle."),
        ("David", "Passt, dann sind wir durch."),
    ],
    "fachbegriffe-1": [
        ("Anna",
         "Der Bauantrag richtet sich nach der OIB-Richtlinie 2 und der ÖNORM B 1300. "
         "Die Bauklasse 4 erlaubt ein Fluchtniveau von höchstens 22 Metern. "
         "Für den zweiten Rettungsweg planen wir eine Außentreppe am Osthof. "
         "Die Brandabschnitte trennen wir mit einer Wand in REI 90."),
    ],
}


# --- Windows-Stimmen (WinRT/OneCore) ----------------------------------------
#
# Absichtlich NICHT System.Speech/SAPI: dort ist auf dieser Maschine nur
# "Hedda Desktop" selektierbar — die moderneren OneCore-Stimmen (Katja,
# Stefan, Michael de-AT) erreicht man nur über die WinRT-API. SAPI schluckt
# den SelectVoice-Fehler obendrein still (non-terminating) und fällt auf
# die Default-Stimme zurück; ein Mehrsprecher-Testsatz wäre dann akustisch
# ein Ein-Sprecher-Testsatz, ohne dass es jemand merkt.

_WINRT_SCRIPT = BENCH_DIR / "winrt_tts.ps1"


def available_german_voices() -> list[str]:
    """Deutsche OneCore-Stimmen, männliche/weibliche abwechselnd sortiert —
    benachbarte Drehbuch-Sprecher bekommen so maximal verschiedene Stimmen."""
    script = (
        "[Windows.Media.SpeechSynthesis.SpeechSynthesizer, "
        "Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime] | Out-Null; "
        "[Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | "
        "Where-Object { $_.Language -like 'de*' } | "
        "ForEach-Object { \"$($_.DisplayName)|$($_.Gender)\" }"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return []
    female = [l.split("|")[0] for l in out.splitlines() if l.endswith("Female")]
    male = [l.split("|")[0] for l in out.splitlines() if l.endswith("Male")]
    # Reißverschluss: F, M, F, M …
    ordered: list[str] = []
    for pair in zip(female, male):
        ordered.extend(pair)
    ordered.extend(female[len(male):] or male[len(female):])
    return ordered


def synthesize_turns(turns: list[tuple[str, str]], voice_by_speaker: dict[str, str],
                     work: Path) -> list[Path]:
    """Alle Turns in einem PowerShell-Lauf über WinRT synthetisieren.

    Texte gehen als UTF-8-JSON-Datei rein — kein Umlaut-Escaping im
    Kommando. Die WinRT-Streams sind 16 kHz mono; `concat_with_pauses`
    prüft das und resampelt notfalls.
    """
    jobs = [
        {"voice": voice_by_speaker[speaker], "text": text,
         "out": str(work / f"turn_{i:03d}.wav")}
        for i, (speaker, text) in enumerate(turns)
    ]
    jobs_file = work / "jobs.json"
    jobs_file.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-File", str(_WINRT_SCRIPT), "-JobsFile", str(jobs_file)],
        check=True, capture_output=True,
    )
    return [Path(j["out"]) for j in jobs]


# --- Zusammensetzen ---------------------------------------------------------


def concat_with_pauses(wavs: list[Path]) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Turns mit Pausen aneinanderhängen. Gibt (audio, spans) zurück,
    spans = (start_ms, end_ms) je Turn für die Referenz-Zeitstempel."""
    pause = np.zeros(int(PAUSE_SEC * SAMPLE_RATE), dtype=np.float32)
    parts: list[np.ndarray] = []
    spans: list[tuple[int, int]] = []
    cursor = 0

    for i, wav in enumerate(wavs):
        data, rate = sf.read(str(wav), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if rate != SAMPLE_RATE:
            # OneCore-Stimmen liefern 16 kHz; falls eine künftige Stimme
            # anders tickt, gleichziehen statt abbrechen. scipy kommt
            # ohnehin mit pyannote.
            from scipy.signal import resample_poly

            from math import gcd

            g = gcd(SAMPLE_RATE, rate)
            data = resample_poly(data, SAMPLE_RATE // g, rate // g).astype("float32")
        start_ms = int(cursor / SAMPLE_RATE * 1000)
        parts.append(data)
        cursor += len(data)
        spans.append((start_ms, int(cursor / SAMPLE_RATE * 1000)))
        if i < len(wavs) - 1:
            parts.append(pause)
            cursor += len(pause)

    return np.concatenate(parts), spans


def write_mp3(audio: np.ndarray, out: Path) -> None:
    import av

    with tempfile.TemporaryDirectory() as td:
        tmp_wav = Path(td) / "full.wav"
        sf.write(str(tmp_wav), audio, SAMPLE_RATE)
        with av.open(str(tmp_wav)) as inp, av.open(str(out), "w") as container:
            ostream = container.add_stream("mp3", rate=44100)
            resampler = av.audio.resampler.AudioResampler(
                format=ostream.format, layout=ostream.layout, rate=ostream.rate
            )
            for frame in inp.decode(inp.streams.audio[0]):
                frame.pts = None
                for rframe in resampler.resample(frame):
                    for packet in ostream.encode(rframe):
                        container.mux(packet)
            for packet in ostream.encode(None):
                container.mux(packet)


def write_reference(turns: list[tuple[str, str]], spans: list[tuple[int, int]],
                    title: str, out: Path) -> None:
    """Referenz im Format des App-Exports — aus dem Drehbuch, NIE aus der
    Pipeline."""
    def ts(ms: int) -> str:
        s = ms // 1000
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    lines = [f"# {title}", "", "## Transkript", ""]
    for (speaker, text), (start_ms, _end) in zip(turns, spans):
        lines += [f"**[{ts(start_ms)}] {speaker}**", "", text, ""]
    out.write_text("\n".join(lines), encoding="utf-8")


# --- Hauptlauf --------------------------------------------------------------


def main() -> int:
    voices = available_german_voices()
    if not voices:
        print("Keine selektierbare deutsche Stimme gefunden — Abbruch.")
        return 1
    print(f"Selektierbare de-Stimmen: {', '.join(voices)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = 0

    for name, turns in SCRIPTS.items():
        mp3_path = OUT_DIR / f"{name}.mp3"
        ref_path = OUT_DIR / f"{name}.reference.md"
        if mp3_path.exists() and ref_path.exists():
            print(f"[übersprungen] {name} existiert")
            continue

        # Sprecher → Stimme, round-robin über die verfügbaren.
        speakers = list(dict.fromkeys(s for s, _ in turns))
        voice_by_speaker = {
            s: voices[i % len(voices)] for i, s in enumerate(speakers)
        }
        if len(voices) < len(speakers):
            print(
                f"[Hinweis] {name}: {len(speakers)} Sprecher, aber nur "
                f"{len(voices)} Stimmen — Stimmen werden doppelt belegt, "
                f"die Referenz behält die Drehbuch-Sprecher."
            )

        print(f"[erzeuge] {name}: {len(turns)} Turns, "
              f"{len(speakers)} Sprecher …")
        with tempfile.TemporaryDirectory() as td:
            wavs = synthesize_turns(turns, voice_by_speaker, Path(td))
            audio, spans = concat_with_pauses(wavs)

        write_mp3(audio, mp3_path)
        write_reference(turns, spans, title=name, out=ref_path)
        duration = len(audio) / SAMPLE_RATE
        print(f"[fertig]  {mp3_path.name} ({duration:.1f} s) + {ref_path.name}")
        generated += 1

    print(f"\n{generated} Testsätze erzeugt in {OUT_DIR}")
    print("Messen mit:  python benchmark/run.py --label <name>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
