# Blitztext → Meeting-Transkriptions-Modus

## Context

Blitztext ist heute eine Windows-Tray-Utility (PyQt6) für lokales Speech-to-Text mit globalem Hotkey: Mikrofon aufnehmen → faster-whisper → Text in aktives Fenster injizieren. Funktioniert und ist in Verwendung. GitHub: `julasim/Blitztext`.

**Ziel:** Zweiter Modus — **Meeting-Transkription**. Audio-Datei-Import (später auch Live-Aufnahme), Speaker-Diarization mit manueller Nachbenennung der Sprecher, leichter LLM-Cleanup (Füllwörter/Wiederholungen, kein Umschreiben). Blitztext wird damit von einer Tray-Utility zu einer **richtigen Desktop-App** mit Bibliothek, Editor, Meeting-Historie. Der Dictate-Modus bleibt parallel nutzbar, wird in Phase 2 ins neue UI integriert.

**Architektur-Entscheidung:** Die bestehende PyQt-UI wird **nicht** ausgebaut. Das neue UI basiert auf einem High-Fidelity-Design-Handoff (Inter/JetBrains Mono, `#09090B`-basierte Palette, Waveforms, drei Surfaces: Workspace / Mini-Widget / Tray-Panel), das Web-Stack voraussetzt. Umsetzung mit **Tauri 2 + React + TypeScript**. Der bestehende Python-Kerncode (`core/audio.py`, `core/transcription.py`, `core/llm.py`, …) bleibt zu ~100 % wiederverwendbar und läuft als **Python-Sidecar** unter der Tauri-Shell. `ui/*.py` wird komplett throwaway.

**Zielbild MVP (Phase 1):** Datei-Import → Pipeline (Whisper word-level + pyannote → Merger → Turns) → Review-Ansicht mit klickbaren Sprechern (Rename-Popover mit 5-Sek-Audio-Snippet) → LLM-Cleanup-Toggle (Ollama lokal) → Markdown-Export. Kein Live-Recording in Phase 1.

---

## Architektur-Überblick

```
┌────────────────────────────────────────────────────────┐
│  Tauri-Shell (Rust)  —  Fenster, Shortcuts, Sidecar-Mgmt │
│  ┌────────────────────────┐   ┌────────────────────────┐ │
│  │ React-Frontend (TS)    │   │ Python-Sidecar (EXE)   │ │
│  │  - Views, Komponenten  │◄──┤  - JSON-RPC-Server     │ │
│  │  - Zustand-Store       │   │  - Whisper + pyannote  │ │
│  │  - Design-Tokens       │   │  - SQLite, Ollama      │ │
│  └──────────┬─────────────┘   └──────────┬─────────────┘ │
│             │                            │               │
│             └──── Tauri invoke ──────────┘               │
│                       │                                  │
│                   JSON-RPC 2.0                           │
│                (ndjson über stdin/stdout)                │
└────────────────────────────────────────────────────────┘
```

- **Transport:** Line-delimited JSON (ndjson) über stdin/stdout des Sidecar-Prozesses. Keine offenen Ports → keine Firewall-Dialoge, sauber an Prozess-Lifetime gekoppelt.
- **Events:** Sidecar pusht Progress-Notifications (JSON-RPC-Notifications ohne `id`) → Rust-Layer rebroadcastet via `window.emit()` → Frontend hört mit `listen()`.
- **Datenhoheit:** SQLite gehört dem Sidecar (Python), Frontend hat nur RPC-Zugriff. Keine Doppel-Pflege von Schemas.

---

## Repo-Layout

### Pfad-Migration

Bestehender Projektpfad: `C:\Users\juliu\OneDrive - Mag. Georg Sima\3_Unternehmen\KI-OS\Blitztext\Blitztext\`

**Neuer Dev-Pfad:** `C:\Users\juliu\Desktop\Blitztext\` (außerhalb OneDrive, vermeidet Sync-Konflikte mit `node_modules/` und `target/`).

Migration-Strategie:
1. `git push -u origin feat/meeting-mode` — Branch aufs Remote sichern.
2. Kompletten Projektordner `C:\Users\juliu\OneDrive...\Blitztext\` nach `C:\Users\juliu\Desktop\Blitztext\` **verschieben** (inkl. `.git/`). Der alte OneDrive-Pfad ist danach leer.
3. `cd C:\Users\juliu\Desktop\Blitztext && git status` — verifizieren: sauber auf `feat/meeting-mode`.
4. Remote-Fetch testen: `git fetch && git log --oneline -5`.

### Ziel-Struktur (nach Phase 1)

```
C:\Users\juliu\Desktop\Blitztext\
├── main.py                         # (legacy) PyQt-Tray, lauffähig
├── core/                           # Shared — wird von legacy UND Sidecar importiert
│   ├── audio.py                    # reuse unverändert (außer MAX_BUFFER_SEC)
│   ├── transcription.py            # + word_timestamps
│   ├── llm.py                      # + _call_ollama_local + cleanup_turn
│   ├── hotkey.py, injector.py, clipboard.py, tts.py   # legacy-only
│   ├── log.py, migration.py, updater.py, update_installer.py, voice_download.py
├── config/                         # unverändert
├── ui/                             # (legacy) PyQt
│
├── sidecar/                        # NEU — Python-Backend für Tauri
│   ├── __main__.py                 # Entry: logging + serve_stdio()
│   ├── rpc.py                      # JSON-RPC 2.0 Dispatcher (ndjson/stdio)
│   ├── rpc_schema.md               # Contract-Doku (Source of Truth)
│   ├── audio_io.py                 # Datei-Decode → 16kHz mono numpy
│   ├── diarization.py              # pyannote.audio Wrapper
│   ├── merger.py                   # Word-TS + Speaker-Segments → Turns
│   ├── meeting_store.py            # SQLite CRUD
│   ├── meeting_pipeline.py         # Orchestration mit Progress-Events
│   ├── events.py                   # Queue für async Notifications
│   └── requirements.txt            # +pyannote.audio, +torch, +soundfile
│
├── app/                            # NEU — Tauri 2 + React 18 + TS
│   ├── src-tauri/                  # Rust-Shell
│   │   ├── Cargo.toml
│   │   ├── tauri.conf.json         # Externals: sidecar-Binary
│   │   ├── binaries/               # Platzhalter für PyInstaller-EXE (per-target)
│   │   └── src/
│   │       ├── main.rs             # Plugin-Setup, Sidecar-Spawn
│   │       ├── sidecar.rs          # SidecarHandle: stdin/stdout-IPC, Auto-Respawn
│   │       ├── commands.rs         # `rpc(method, params)` invoke-Command
│   │       └── events.rs           # Event-Bridge Sidecar→Window
│   ├── src/                        # React
│   │   ├── main.tsx, App.tsx
│   │   ├── styles/
│   │   │   ├── tokens.css          # Design-Tokens (aus Handoff)
│   │   │   └── globals.css
│   │   ├── lib/rpc.ts, lib/types.ts
│   │   ├── state/useMeetingStore.ts, useAppStore.ts
│   │   ├── components/             # Sidebar, TranscriptView, SpeakerList, …
│   │   └── views/                  # Library, MeetingImport, MeetingProcessing, MeetingReview, Settings
│   ├── vite.config.ts, tsconfig.json, package.json, index.html
│
├── build.spec                      # legacy PyInstaller
├── build-sidecar.spec              # NEU — PyInstaller für Sidecar
├── installer/                      # InnoSetup (wird in Phase 2 auf Tauri-Output umgebaut)
└── requirements.txt                # legacy
```

---

## Phase 0 — Setup

| # | Schritt | Wer | Verifikation |
|---|---|---|---|
| 0.1 | Rust-Toolchain installieren: `winget install Rustlang.Rustup` (Standard-Profil, MSVC-Toolchain) | User manuell | `rustc --version` → ≥ 1.77 |
| 0.2 | Tauri-CLI global: `cargo install tauri-cli --version "^2.0"` | User einmalig | `cargo tauri --version` |
| 0.3 | Repo-Move: feat-Branch pushen, Ordner nach Desktop verschieben (s. oben) | User | `git status` in neuem Pfad sauber |
| 0.4 | Python 3.11-venv für Sidecar (nicht 3.14 — `pyannote.audio 3.x` + `torch 2.4` sind auf 3.11 stabilisiert): `py -3.11 -m venv .venv-sidecar` | Automatisiert | `python -c "import sys; print(sys.version)"` |
| 0.5 | Sidecar-Deps installieren: `sidecar/requirements.txt` mit `faster-whisper`, `pyannote.audio==3.3.*`, `torch==2.4.*+cu121`, `soundfile`, `numpy`, `httpx` | Automatisiert | `python -c "import pyannote.audio, torch; print(torch.cuda.is_available())"` → `True` |
| 0.6 | HuggingFace-Account + pyannote-Lizenzen (s. eigene Section unten) | User manuell, ~5 Min | Token im Keyring unter `blitztext/hf_token` |
| 0.7 | Ollama starten + Default-Modell pullen: `ollama serve` (Background) + `ollama pull qwen2.5:7b-instruct` | User | `curl http://127.0.0.1:11434/api/tags` zeigt Modell |
| 0.8 | Tauri-Scaffold im `app/`-Ordner: `npm create tauri-app@latest app -- --template react-ts --identifier io.julasim.blitztext --manager npm` | Automatisiert | `cd app && cargo tauri dev` öffnet Fenster |
| 0.9 | Frontend-Deps: `npm i zustand @tauri-apps/api @tauri-apps/plugin-shell @tauri-apps/plugin-dialog @tauri-apps/plugin-fs lucide-react @tanstack/react-virtual` | Automatisiert | `npm ls` ohne Fehler |
| 0.10 | CUDA-Check: `nvidia-smi` + Python-Check | User/Automatisiert | RTX 4060 sichtbar, `torch.cuda.is_available()` = True |
| 0.11 | Smoke-Test: Minimaler Sidecar-Stub antwortet auf `ping` | Automatisiert | `echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' \| python -m sidecar` gibt `{"result":{"ok":true,...}}` |

### Phase-0-Gate: HuggingFace-Setup für pyannote (User-Schritte)

Ohne diesen Block lädt pyannote die Gated Models nicht. Wörtlich:

1. Account anlegen: https://huggingface.co/join.
2. **Lizenz-Akzeptanz für beide Modelle** (eingeloggt Button „Agree and access repository" klicken):
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Access-Token erstellen: https://huggingface.co/settings/tokens → „New token" → Typ **Read** → Name `blitztext-pyannote` → Token kopieren.
4. Token in Blitztext hinterlegen: entweder Settings-UI (später) oder vorab manuell:
   ```powershell
   python -c "import keyring; keyring.set_password('blitztext', 'hf_token', 'hf_xxxxx')"
   ```

Smoke-Test ob alles sitzt:
```python
from pyannote.audio import Pipeline
import keyring
tok = keyring.get_password('blitztext', 'hf_token')
p = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=tok)
print("OK", p)
```

---

## Phase 1 — Meeting-MVP

Die Reihenfolge ist bindend: RPC-Contract zuerst, dann Sidecar von unten nach oben, dann Tauri-Shell, dann Frontend. Keine Abkürzungen — der Contract ist die Achse, an der alles hängt.

### Schritt 1 — JSON-RPC-Contract (**zuerst!**)

Artefakte: `sidecar/rpc_schema.md` (Source of Truth) + `app/src/lib/types.ts` (TS-Mirror, manuell gepflegt).

**Methoden** (Request → Response):

| Method | Params | Result |
|---|---|---|
| `ping` | — | `{ok, version}` |
| `config.get` | — | `{models_dir, appdata, cuda_available, ollama_available, whisper_models: string[]}` |
| `meeting.import_file` | `{path, title?}` | `{meeting_id}` |
| `meeting.list` | `{limit?, offset?}` | `Meeting[]` |
| `meeting.get` | `{id}` | `MeetingFull` |
| `meeting.delete` | `{id}` | `{ok}` |
| `meeting.set_title` | `{id, title}` | `{ok}` |
| `speaker.rename` | `{meeting_id, speaker_id, name}` | `{ok}` |
| `speaker.merge` | `{meeting_id, source_id, target_id}` | `{ok, merged_turns}` |
| `speaker.sample` | `{meeting_id, speaker_id, max_sec?}` | `{wav_path}` |
| `cleanup.run` | `{meeting_id, model?}` | `{ok}` |
| `cleanup.status` | `{meeting_id}` | `{state, progress}` |
| `export.markdown` | `{meeting_id, use_cleanup, path}` | `{ok, bytes}` |
| `settings.update` | `{...}` | `{ok}` |

**Events** (Server-Push, Notifications):

| Event | Payload |
|---|---|
| `meeting.progress` | `{meeting_id, stage, pct, eta_sec}` — stages: `decode \| transcribe \| diarize \| merge \| persist` |
| `meeting.done` | `{meeting_id}` |
| `meeting.error` | `{meeting_id, stage, message}` |
| `cleanup.turn_done` | `{meeting_id, turn_id}` |

**TypeScript-Typen** (`app/src/lib/types.ts`, parallel als `@dataclass` in `sidecar/rpc.py`):

```ts
type Turn = { id:string; speaker_id:string; idx:number;
              start_ms:number; end_ms:number;
              text_raw:string; text_clean?:string;
              words:{t0:number;t1:number;w:string}[];
              overlap_flag:boolean }
type Speaker = { id:string; label:string; name?:string; color:string;
                 word_count:number; duration_ms:number; share_pct:number }
type Meeting = { id:string; title:string; duration_ms:number;
                 created_at:string; status:'processing'|'ready'|'error' }
type MeetingFull = Meeting & { audio_path:string; language:string;
                               whisper_model:string; speakers:Speaker[]; turns:Turn[] }
```

### Schritt 2 — Python-Sidecar (strikte Reihenfolge)

| # | Datei | Zweck | Wiederverwendung / Neu |
|---|---|---|---|
| 2.1 | `sidecar/audio_io.py` | `load_audio(path) -> (np.ndarray@16kHz mono, duration_ms)`. Unterstützte Formate MVP: WAV, MP3, FLAC, OGG über `soundfile` + `librosa.resample`. M4A → Phase 2 (ffmpeg). | Neu, ~80 LOC |
| 2.2 | `sidecar/meeting_store.py` | SQLite: `init_db()`, `create_meeting()`, `upsert_turns()`, `get_meeting()`, `list_meetings()`, `delete_meeting()`, `rename_speaker()`, `merge_speakers()`. DB liegt unter `%APPDATA%\Blitztext\meetings.db`, Audio unter `%APPDATA%\Blitztext\meetings\<uuid>\source.<ext>`. | Neu, ~250 LOC, `sqlite3` stdlib |
| 2.3 | `core/transcription.py` (Erweiterung) | Neue Methode `transcribe_with_words(audio, language)` → nutzt faster-whisper `word_timestamps=True`. Alter Code bleibt. | Erweiterung, +60 LOC |
| 2.4 | `sidecar/diarization.py` | `DiarizationPipeline` Klasse: Cached pyannote-Pipeline mit CUDA, HF-Token aus Keyring. Methode `diarize(audio_ndarray, min_speakers?, max_speakers?) -> [{start, end, speaker_label}]`. | Neu, ~120 LOC |
| 2.5 | `sidecar/merger.py` | `merge(words, segments) -> (turns, speakers)`. Algorithmus: für jedes Wort finde pyannote-Segment mit max. Timestamp-Overlap; bei Ambiguität (Kreuzreden) `overlap_flag=True`. Konsekutive Wörter gleichen Sprechers mit Gap < 1.2s → ein Turn. Min-Segment-Länge 300ms (kürzere an Nachbarn ziehen). Speaker-Stats: Wortzahl, Dauer-Summe, %-Anteil. Farbpalette aus Design (12 Farben). | Neu, ~180 LOC |
| 2.6 | `core/llm.py` (Erweiterung) | Neue Funktion `_call_ollama_local(system_prompt, text, model)` → POST `http://127.0.0.1:11434/api/chat`, stream=False. Zweite Funktion `cleanup_turn(prev_text, turn_text, next_text, model)` mit Prompt „Füllwörter raus, Wiederholungen weg, keine inhaltlichen Änderungen". | Erweiterung, +70 LOC. Referenz: bestehender `_call_ollama_cloud` in `core/llm.py:45-52` als Template für Body-Struktur. |
| 2.7 | `sidecar/meeting_pipeline.py` | `run_import(file_path, on_event) -> meeting_id`: Stages sequenziell (decode 5%, transcribe 55%, diarize 30%, merge 5%, persist 5%). `run_cleanup(meeting_id, on_event)`: per Turn LLM-Call mit Nachbar-Kontext. Schreibt nach jedem Stage in die DB (Resume-freundlich). | Neu, ~200 LOC |
| 2.8 | `sidecar/events.py` | Thread-safe Queue, emit(name, payload). | Neu, ~30 LOC |
| 2.9 | `sidecar/rpc.py` | NDJSON-Reader-Loop, `@method("name")`-Decorator, Error-Mapping (Python-Exception → JSON-RPC-Error), Event-Writer (pullt aus events.py). | Neu, ~220 LOC |
| 2.10 | `sidecar/__main__.py` | Logging nach `%APPDATA%\Blitztext\sidecar.log`, Signal-Handler, `rpc.serve_stdio()`. | Neu, ~40 LOC |

**DB-Schema** (`sidecar/meeting_store.py`):

```sql
PRAGMA schema_version = 1;

CREATE TABLE meetings (
  id TEXT PRIMARY KEY, title TEXT, audio_path TEXT,
  duration_ms INTEGER, language TEXT, created_at TEXT,
  status TEXT, whisper_model TEXT, diar_model TEXT);

CREATE TABLE speakers (
  id TEXT PRIMARY KEY, meeting_id TEXT REFERENCES meetings(id) ON DELETE CASCADE,
  label TEXT, name TEXT, color TEXT);

CREATE TABLE turns (
  id TEXT PRIMARY KEY, meeting_id TEXT REFERENCES meetings(id) ON DELETE CASCADE,
  speaker_id TEXT REFERENCES speakers(id),
  idx INTEGER, start_ms INTEGER, end_ms INTEGER,
  text_raw TEXT, text_clean TEXT, words_json TEXT, overlap_flag INTEGER);

CREATE INDEX idx_turns_meeting_idx ON turns(meeting_id, idx);
```

### Schritt 3 — Tauri-Rust-Shell

| # | Datei | Inhalt | LOC |
|---|---|---|---|
| 3.1 | `app/src-tauri/tauri.conf.json` | App-ID `io.julasim.blitztext`, Window 1280×800 minSize 960×640, `externalBin: ["binaries/blitztext-sidecar"]`, capabilities für shell/dialog/fs | 80 |
| 3.2 | `app/src-tauri/src/sidecar.rs` | `SidecarHandle`: Mutex<Child>, Line-Reader-Thread parst ndjson, Map<id, oneshot::Sender> für Responses, Broadcast-Channel für Notifications, Timeout 30s, Auto-Respawn bei Crash (exponential backoff, max 3 Versuche) | 250 |
| 3.3 | `app/src-tauri/src/commands.rs` | `#[tauri::command] async fn rpc(method, params) -> Result<Value>`: serialisiert JSON-RPC-Request, wartet auf matching `id` aus SidecarHandle. Plus `pick_meeting_file()` → `dialog::FileDialogBuilder`. | 120 |
| 3.4 | `app/src-tauri/src/events.rs` | Subscriber-Loop liest Broadcast aus SidecarHandle, emit via `app.emit_all("sidecar-event", ...)` | 60 |
| 3.5 | `app/src-tauri/src/main.rs` | Tauri-Builder, `.plugin(tauri_plugin_shell::init())`, `.plugin(tauri_plugin_dialog::init())`, Setup-Hook startet Sidecar via `ShellExt::sidecar`, Shutdown-Hook killt Subprozess sauber | 80 |

Begründung für einen generischen `rpc`-Command statt typisierten Einzel-Commands: RPC-Schemas sind auf Python-Seite validiert, Typ-Sicherheit bleibt im Frontend via TypeScript. Rust-Zwischenschicht ist nur Transport.

### Schritt 4 — React-Frontend

Reihenfolge:

| # | Artefakt | Inhalt |
|---|---|---|
| 4.1 | `app/src/styles/tokens.css` | CSS-Custom-Properties aus Design-Handoff: `--bt-ink:#09090B`, `--bt-paper:#FAFAFA`, `--bt-line:#E5E7EB`, `--bt-red:#EF4444`, `--bt-green:#10B981`, …, plus `--font-app:'Inter'`, `--font-mono:'JetBrains Mono'`. Fonts via `@fontsource/inter` + `@fontsource/jetbrains-mono`. |
| 4.2 | `app/src/lib/rpc.ts` | `call<T>(method, params): Promise<T>` wrappt `invoke('rpc', {method, params})`. `subscribe(event, handler): Unsubscribe` wrappt `listen('sidecar-event', ...)` mit Filter auf `event`-Feld. |
| 4.3 | `app/src/lib/types.ts` | TypeScript-Spiegel der RPC-Schemas (Turn, Speaker, Meeting, MeetingFull). |
| 4.4 | `app/src/state/useMeetingStore.ts` | Zustand-Store: `meetings`, `active: MeetingFull \| null`, `importProgress`, `cleanupActive`. Actions: `import(path)`, `load(id)`, `renameSpeaker(sid, name)` (optimistisch), `mergeSpeakers(src, tgt)`, `toggleCleanup()`. |
| 4.5 | `app/src/views/Library.tsx` | Sidebar + Meeting-Liste. „Neu importieren"-Button oben rechts. |
| 4.6 | `app/src/views/MeetingImport.tsx` | Große Drop-Zone (HTML5-DragDrop, Fallback-Button → `pick_meeting_file`), Format-Whitelist, Titel-Eingabe, CTA „Transkribieren starten". |
| 4.7 | `app/src/views/MeetingProcessing.tsx` | Stage-Bar mit 5 Segmenten, ETA, abbrechbar. Subscribed `meeting.progress`. |
| 4.8 | `app/src/views/MeetingReview.tsx` | **Hauptansicht**. Drei-Spalten: links `SpeakerList` (Farbpunkt, Name, Anteil), Mitte `TranscriptView` mit `@tanstack/react-virtual` (weil lange Meetings 2000+ Turns), rechts `MetaPanel` + `CleanupToggle` + Export-Buttons. |
| 4.9 | `app/src/components/SpeakerList.tsx` + `SpeakerRenamePopover.tsx` | Speaker anklicken → Popover öffnet: Audio-Snippet (HTML5 `<audio>` mit `speaker.sample`-WAV) + Namens-Eingabe + „Mit anderem Sprecher zusammenfassen"-Dropdown. |
| 4.10 | `app/src/components/TurnRow.tsx` | `[HH:MM:SS] [Sprecher]  Text` in einer Zeile. Toggle zwischen `text_raw` und `text_clean`. `overlap_flag` zeigt dezente Warnung („überlappende Rede"). |
| 4.11 | `app/src/views/Settings.tsx` | Whisper-Modell, Cleanup-Modell (Ollama), HF-Token setzen, Theme (nur Platzhalter — Light-Only MVP). |

Dictate-Modus wird im Frontend in Phase 1 **nicht** eingebaut — der bestehende `main.py` bleibt für Dictate lauffähig.

### Schritt 5 — Build & Packaging

| # | Schritt | Detail |
|---|---|---|
| 5.1 | `build-sidecar.spec` für PyInstaller | Onedir (nicht onefile — Startzeit), `--collect-data pyannote.audio`, `--hidden-import` für `torch._C`, `lightning_fabric`, `speechbrain`, `asteroid_filterbanks`. Output: `dist/blitztext-sidecar/blitztext-sidecar.exe` + ganzer Ordner |
| 5.2 | Sidecar in Tauri einhängen | `dist/blitztext-sidecar/` nach `app/src-tauri/binaries/` kopieren, EXE umbenennen zu `blitztext-sidecar-x86_64-pc-windows-msvc.exe` (Tauri-Namenskonvention). `tauri.conf.json.externalBin` + `resources: ["binaries/blitztext-sidecar/*"]` |
| 5.3 | Frontend-Build | `cd app && npm run build` |
| 5.4 | Tauri-Bundle | `cargo tauri build` → NSIS + MSI in `app/src-tauri/target/release/bundle/` |
| 5.5 | Modelle nicht bundlen | First-Run-Download (pyannote lädt automatisch bei erster Pipeline-Init, Whisper via bestehendem `voice_download.py`-Pattern) |

---

## Phase 2 — Live-Recording + Dictate-Migration (Outline)

- **Live-Meeting-Recording:** `core/audio.py` als Basis (MAX_BUFFER_SEC aufheben). Streaming-Chunker in Sidecar (30s-Fenster, 2s Overlap), Whisper inkrementell, pyannote **am Ende** über ganze WAV. Live-UI zeigt Wort-Stream ohne Diarization; Turns werden erst nach Stop gebildet.
- **System-Loopback** (Teams/Zoom mithören): WASAPI via `pyaudiowpatch`, Mic+Loopback in 2-Kanal-WAV, pyannote auf Merged-Mono.
- **Dictate-Migration:** `hotkey.py` → `@tauri-apps/plugin-global-shortcut`. `injector.py` + `clipboard.py` bleiben Python, exponiert als `dictate.inject(text)` RPC. Recording-Overlay + Mini-Widget + Tray-Panel aus Design-Handoff nachbauen. Danach kann `main.py` + `ui/*` deprecated werden.
- **Settings-Unification:** PyQt-Settings → `views/Settings.tsx`. `config/settings.py` bleibt Single-Source-of-Truth, Frontend greift via RPC zu.

---

## Phase 3 — Polish (Outline)

- Voice-Enrollment: Sprecher-Embeddings persistent, Auto-Match bei neuen Meetings.
- Exports: DOCX (`python-docx`), SRT/VTT, PDF (`weasyprint`).
- Dark-Mode (Design aktuell Light-Only, Tokens invertierbar).
- FTS5-Suche über alle Meetings.
- Auto-Summary per LLM.
- Signed Build + Tauri-Auto-Updater (bestehender `updater.py` als Referenz).

---

## Risiken & Mitigation

| Risiko | Mitigation |
|---|---|
| **pyannote auf Windows** — gated Model, Torch-Version-Mismatch häufig | Pin `pyannote.audio==3.3.*` + `torch==2.4.*+cu121`. HF-Token im Keyring. Smoke-Test-Skript in Phase 0. CPU-Fallback bei CUDA-Init-Fehler. |
| **PyInstaller-Sidecar 500 MB+** (torch+cuDNN+pyannote) | MVP akzeptieren. CUDA-DLLs gezielt via `--add-binary` (nur `cudnn_ops*`, `cudart*`, kein volles Toolkit). Phase 2: ONNX-Export für pyannote prüfen. |
| **Merge-Edge-Cases** (Kreuzreden, Sprecher-Split, pyannote erzeugt 10+ Sprecher bei 2-Personen-Audio) | `min_speakers`/`max_speakers`-Hints an pyannote. `speaker.merge` als First-Class-Feature. Min-Segment-Länge 300ms. Overlap-Flag im Turn-Modell, UI zeigt dezent. |
| **Tauri-2-Jugend / Rust-Lernkurve** | Rust-Code minimal halten (~500 LOC). Abort-Gate am Ende Phase 0: wenn Sidecar-Spawn in 2 Tagen nicht stabil, Electron-Switch dokumentieren. |
| **Ollama nicht laufend** | Sidecar pollt `http://127.0.0.1:11434/api/tags` beim Start. Cleanup-Feature graceful disablen, UI zeigt Banner „Ollama nicht erreichbar". |
| **Desktop-Pfad enthält Umlaute/Sonderzeichen** (`C:\Users\juliu\Desktop\`) | Juliu hat kein Umlaut → unproblematisch. Falls später Umlaute: Tauri-NSIS kennt Probleme mit Non-ASCII-Paths, ggf. `C:\dev\blitztext`-Pfad bevorzugen. |

---

## Verification (End-to-End-Smoke-Test nach Phase 1)

1. **Cold Start:** `cd C:\Users\juliu\Desktop\Blitztext\app && cargo tauri dev` — Fenster öffnet, Library-View leer, Statusbar zeigt „Sidecar ready, CUDA: ja, Ollama: ja".
2. **Import:** Drag 10-minütige Test-WAV auf Drop-Zone → `MeetingProcessing`-View erscheint → Stage-Bar läuft durch alle 5 Stages → automatische Weiterleitung zu `MeetingReview`.
3. **Review:** Linke Spalte zeigt 2–5 Sprecher mit Farben und %-Anteilen. Mitte zeigt Turns mit Timestamp und Sprecher-Prefix. Rechts zeigt Meta + Cleanup-Toggle (aus).
4. **Speaker-Rename:** Klick auf „Speaker 1" → Popover öffnet → Audio-Snippet spielt ab → Namen eingeben „Julius" → bestätigen → alle Turns zeigen jetzt „Julius".
5. **Speaker-Merge:** Klick auf „Speaker 2" → „mit Speaker 3 zusammenfassen" → alle Turns beider Sprecher jetzt unter einem.
6. **Cleanup:** Toggle „LLM-Cleanup" → aktiv → Fortschrittsanzeige per Turn → fertige Turns zeigen gesäuberten Text. Toggle zurück: Original sichtbar.
7. **Export:** „Markdown exportieren" → Dialog → Datei schreiben → öffnen: klar strukturiertes Meeting-Protokoll mit Sprechern, Timestamps, Text.
8. **Library:** Zurück zur Library → Meeting in Liste. Klick → Review wieder offen. Lösch-Button → Meeting + DB-Rows + Audio-File weg.
9. **Relaunch:** App schließen, neu starten → Meeting ist persistent da.
10. **Sidecar-Resilience:** `taskkill /F /IM blitztext-sidecar.exe` während Idle → Rust-Layer respawnt → Frontend zeigt kurz „Reconnecting", dann wieder einsatzbereit.

---

## Kritische Dateien für Implementierung (Referenzen)

- `C:\Users\juliu\Desktop\Blitztext\sidecar\rpc.py` — JSON-RPC-Dispatcher
- `C:\Users\juliu\Desktop\Blitztext\sidecar\meeting_pipeline.py` — Orchestration
- `C:\Users\juliu\Desktop\Blitztext\sidecar\merger.py` — Word-zu-Sprecher-Merge
- `C:\Users\juliu\Desktop\Blitztext\sidecar\diarization.py` — pyannote-Wrapper
- `C:\Users\juliu\Desktop\Blitztext\app\src-tauri\src\sidecar.rs` — Rust-IPC
- `C:\Users\juliu\Desktop\Blitztext\app\src\views\MeetingReview.tsx` — Haupt-UI
- `C:\Users\juliu\Desktop\Blitztext\core\audio.py` — **bestehend**, unverändert reusen
- `C:\Users\juliu\Desktop\Blitztext\core\transcription.py` — **bestehend**, um `word_timestamps=True` erweitern
- `C:\Users\juliu\Desktop\Blitztext\core\llm.py` — **bestehend**, `_call_ollama_local` + `cleanup_turn` ergänzen (Referenz: bestehende `_call_ollama_cloud` Body-Struktur)

---

## Entschiedene Defaults (können später geändert werden)

- Whisper-Default Meeting-Mode: `large-v3-turbo` bei CUDA, sonst `medium`. Auto-Select via `config.get`.
- Ollama-Default Cleanup: `qwen2.5:7b-instruct` (schnell + gut bei Deutsch).
- RPC-Transport: ndjson über stdin/stdout.
- Export MVP: nur Markdown.
- DB-Migrationen: manuelle `schema_version`-Steps, kein Alembic.
- UI-Sprache: Deutsch, i18n-Grundstruktur vorbereitet (Phase 3).
- Sprecher-Farben: 12-Farben-Palette round-robin aus Design.

---

## Phase-0-Arbeitspaket (nächster konkreter Schritt nach Plan-Approval)

1. User: Rust installieren (`winget install Rustlang.Rustup`).
2. User: Repo aufs Remote pushen, dann Ordner nach Desktop verschieben.
3. User: HuggingFace-Account + pyannote-Lizenzen + Token ins Keyring (Schritte oben).
4. User: Ollama starten + `qwen2.5:7b-instruct` pullen.
5. Ich: `sidecar/requirements.txt` anlegen + venv bootstrappen.
6. Ich: Tauri-Scaffold in `app/` anlegen + Frontend-Deps installieren.
7. Ich: Minimaler Sidecar-Stub mit `ping`-Methode, Rust-Shell spawned Sidecar, Frontend ruft `ping` → zeigt Version. Das ist das Phase-0-Gate.

Danach Phase 1 in strikter Reihenfolge: RPC-Contract → Sidecar (unten nach oben) → Rust → Frontend → Build.
