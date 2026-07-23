# Blitztext

Transkribiert Audiodateien lokal auf Windows — MP3, WAV, M4A, FLAC, OGG.
Mit Sprecher-Trennung, optionalem LLM-Cleanup und Markdown-Export.
Alles on-device: kein Cloud-Dienst, keine offenen Ports, kein Mikrofonzugriff.

## Repository-Struktur

| Pfad | Rolle |
|---|---|
| `app/` | Tauri 2 + React + TypeScript. Die Desktop-App; spawnt den Sidecar als Child-Prozess. |
| `sidecar/` | Python-Backend. JSON-RPC 2.0 über stdin/stdout, siehe `sidecar/rpc_schema.md`. Besitzt die SQLite-DB. |
| `core/` | Geteilte Bausteine: Whisper (`transcription.py`), Ollama-Cleanup (`llm.py`), Log. |
| `tests/` | pytest — siehe unten. |
| `transcribe.py` | CLI: eine Audiodatei durch die volle Pipeline → Markdown. Ohne GUI. |
| `PLAN.md` | Roadmap des Umbaus. Phase 2 (Dictate-Migration) ist mit der Fokussierung hinfällig. |
| `BUILD.md` | Release-Prozess (PyInstaller-Sidecar + Tauri-MSI). |

Zwei Rückbauten am 2026-07-23, beide in der Historie erhalten: der PyQt-Tray
(v1.0.25, liegt unverändert auf Branch `main`) und die Mikrofon-Funktionen
(Diktat per Hotkey, Live-Mitschnitt). Blitztext ist seither ein reines
Datei-Werkzeug.

## Voraussetzungen

Rust + MSVC Build Tools, Python 3.11, Node 20+, Ollama (für den Cleanup) und
ein HuggingFace-Account mit akzeptierten pyannote-Lizenzen. Details in
`PLAN.md` § *Phase 0 — Setup*.

## Dev-Setup

```powershell
# Python-Sidecar (CUDA-Index ist Pflicht, sonst kommt Torch ohne GPU-Support)
python3.11 -m venv .venv-sidecar
.\.venv-sidecar\Scripts\pip install -r sidecar\requirements.txt `
  --index-url https://download.pytorch.org/whl/cu121 `
  --extra-index-url https://pypi.org/simple

# Frontend + Tauri
cd app
npm install
npx tauri dev        # kein `npm run tauri` — das Script gibt es nicht
```

Im Dev-Modus startet die Rust-Shell `python -m sidecar` aus `.venv-sidecar`;
ein gebauter Sidecar wird dafür nicht gebraucht.

## Tests

```powershell
.\.venv-sidecar\Scripts\python.exe -m pytest            # Standardlauf, ~2 Sekunden
.\.venv-sidecar\Scripts\python.exe -m pytest --slow     # + Whisper/pyannote über eine echte MP3
.\.venv-sidecar\Scripts\python.exe -m pytest --ollama   # + LLM-Cleanup gegen lokales Ollama
```

Der Standardlauf braucht weder Modelle noch Ollama noch Netz. Was teuer ist,
trägt einen Marker und kommt nur auf Zuruf mit — sonst läuft die Suite
niemand. Jeder Test bekommt über die `store`-Fixture eine eigene DB in einem
Temp-Verzeichnis; die echte Meeting-DB wird nie angefasst.
