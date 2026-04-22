# Blitztext

Lokaler Speech-to-Text-Desktop für Windows. Dictate per globalem Hotkey und —
in Arbeit — Meeting-Transkription mit Sprecher-Diarization und LLM-Cleanup.
Alles on-device.

## Repository-Struktur

| Pfad | Rolle |
|---|---|
| `main.py`, `core/`, `config/`, `ui/` | **Legacy** Tray-Utility (PyQt6) — aktuell die ausgelieferte Version (v1.0.25). Bleibt lauffähig, bis der neue Tauri-Build in Phase 2 Dictate übernimmt. |
| `sidecar/` | **Neu** — Python-Backend für die Tauri-App. JSON-RPC-Server über stdin/stdout. Siehe `sidecar/rpc_schema.md` für den Contract. |
| `app/` | **Neu** — Tauri 2 + React + TypeScript. Eigentliche Desktop-App, die den Sidecar als Child-Prozess spawnt. |
| `PLAN.md` | Verbindliche Roadmap für den Umbau (Phase 0 Setup → Phase 1 Meeting-MVP → Phase 2 Dictate-Migration). |

## Dev-Setup (Meeting-Modus-Zweig)

Siehe `PLAN.md` § *Phase 0 — Setup* für die vollständige Liste. Vorausgesetzt:
Rust + MSVC Build Tools, Python 3.11, Node 20+, Ollama, HuggingFace-Account
mit akzeptierten pyannote-Lizenzen.

```powershell
# Python-Sidecar
py -3.11 -m venv .venv-sidecar
.\.venv-sidecar\Scripts\pip install -r sidecar\requirements.txt

# Frontend + Tauri
cd app
npm install
npm run tauri dev
```

## Legacy-Build (Dictate-Tray)

```powershell
pip install -r requirements.txt
pyinstaller build.spec
```

Produziert `dist/Blitztext/Blitztext.exe` + InnoSetup-Installer unter `dist-installer/`.
Siehe `BUILD.md`.
