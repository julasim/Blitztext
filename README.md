# Blitztext

Transkribiert Audiodateien lokal auf Windows — MP3, WAV, M4A, FLAC, OGG.
Mit Sprecher-Trennung, Fachvokabular, optionalem LLM-Cleanup und
Markdown-Export. Dateien und ganze Ordner laufen als Warteschlange durch,
ein Auftrag nach dem anderen.

**Ausschließlich lokale Modelle.** Whisper, Parakeet und pyannote laufen auf
dem Rechner, der Cleanup gegen Ollama auf `127.0.0.1`. Keine Cloud-Modelle,
keine API-Keys, keine Telemetrie, keine offenen Ports, kein Mikrofonzugriff.
Ins Netz geht die App nur, um die Modelle **einmal herunterzuladen** — danach
arbeitet sie offline.

## Was drin ist

| | |
|---|---|
| **Transkription** | Whisper `large-v3` / `turbo` / `medium` (GPU) oder Parakeet TDT v3 (CPU, ~600 MB, 25 europäische Sprachen). Pro Import wählbar. |
| **Sprecher-Trennung** | pyannote 4 mit `speaker-diarization-community-1`, auf der GPU. Fällt sie aus, läuft der Import mit einem Sprecher weiter statt abzubrechen. |
| **Fachvokabular** | Dauerhafte Firmenliste in den Einstellungen plus ein Feld pro Import. Hilft Whisper bei Normbezeichnungen und Namen. |
| **Warteschlange** | Seriell, abbrechbar, übersteht einen Absturz (Zustand in der DB). Ein fehlgeschlagener Auftrag hält die übrigen nicht auf. |
| **Cleanup** | Zwei Stufen: *wortgetreu* (nur Füllwörter und Stotterer) und *lesbar* (zusätzlich Satzzeichen). Der Rohtext bleibt immer erhalten. |
| **Export** | Markdown, wahlweise mit oder ohne Cleanup. |

## Repository-Struktur

| Pfad | Rolle |
|---|---|
| `app/` | Tauri 2 + React + TypeScript. Die Desktop-App; spawnt den Sidecar als Child-Prozess. |
| `sidecar/` | Python-Backend. JSON-RPC 2.0 über stdin/stdout, siehe `sidecar/rpc_schema.md`. Besitzt die SQLite-DB und die Warteschlange. |
| `core/` | Modell-Wrapper: Whisper (`transcription.py`), Parakeet (`parakeet.py`), Ollama-Cleanup (`llm.py`), Log. |
| `benchmark/` | Messaufbau: WER, Halluzinationsschleifen und Sprecheranzahl gegen korrigierte Referenzen. Nicht Teil der App. |
| `tests/` | pytest — siehe unten. |
| `transcribe.py` | CLI: eine Audiodatei durch die volle Pipeline → Markdown. Ohne GUI. |
| `BUILD.md` | Release-Prozess (PyInstaller-Sidecar + portabler Ordner). |
| `PLAN.md` | **Historisch** (April 2026). Nennt gelöschte Dateien; für die Architektur-Begründungen weiter nützlich, nicht als Aufgabenliste. |

Zwei Rückbauten am 2026-07-23, beide in der Historie erhalten: der PyQt-Tray
(v1.0.25, liegt unverändert auf Branch `main`) und die Mikrofon-Funktionen
(Diktat per Hotkey, Live-Mitschnitt). Blitztext ist seither ein reines
Datei-Werkzeug.

## Voraussetzungen

Rust + MSVC Build Tools, Python 3.11, Node 20+, optional Ollama (für den
Cleanup) und ein HuggingFace-Account, der die Bedingungen von
`pyannote/speaker-diarization-community-1` akzeptiert hat.

## Dev-Setup

```powershell
# Python-Sidecar (CUDA-Index ist Pflicht, sonst kommt Torch ohne GPU-Support)
python3.11 -m venv .venv-sidecar
.\.venv-sidecar\Scripts\python.exe -m pip install -r sidecar\requirements.txt `
  --index-url https://download.pytorch.org/whl/cu128 `
  --extra-index-url https://pypi.org/simple

# Frontend + Tauri
cd app
npm install
npx tauri dev        # kein `npm run tauri` — das Script gibt es nicht
```

Im Dev-Modus startet die Rust-Shell `python -m sidecar` aus `.venv-sidecar`;
ein gebauter Sidecar wird dafür nicht gebraucht.

## Kommandozeile

```powershell
.\.venv-sidecar\Scripts\python.exe transcribe.py "besprechung.mp3" `
  --vocabulary "ÖNORM, OIB-Richtlinie, Bewehrung" `
  --cleanup --cleanup-mode readable
```

## Tests

```powershell
.\.venv-sidecar\Scripts\python.exe -m pytest            # 152 Tests, ~12 s
.\.venv-sidecar\Scripts\python.exe -m pytest --slow     # + Whisper/pyannote über eine echte MP3
.\.venv-sidecar\Scripts\python.exe -m pytest --ollama   # + LLM-Cleanup gegen lokales Ollama
```

Der Standardlauf braucht weder Modelle noch Ollama noch Netz. Was teuer ist,
trägt einen Marker und kommt nur auf Zuruf mit — sonst läuft die Suite
niemand. Jeder Test bekommt über die `store`-Fixture eine eigene DB in einem
Temp-Verzeichnis; die echte Meeting-DB wird nie angefasst.
