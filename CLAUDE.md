<!--
ANWEISUNG AN CLAUDE: Diese Datei zuerst lesen, um den Ordner zu verstehen.
Bevor du die Arbeit in diesem Ordner beendest: diese Datei aktualisieren —
neue Entscheidungen in den Status, erledigte Punkte aus "Offene Punkte"
entfernen, neue Dateien in die Landkarte, "Zuletzt aktualisiert" + Änderungslog
pflegen. Stufe 1 reicht meist; Stufe 2 nur lesen, wenn die Aufgabe es verlangt.
-->

# Blitztext

Zuletzt aktualisiert: 2026-07-23

## Worum geht's

**Transkribiert Audiodateien lokal** (MP3, WAV, M4A, FLAC, OGG) auf Windows:
Import → Whisper → Sprecher-Trennung → Review → LLM-Cleanup → Export.
Eigenes Produkt von Julius (GitHub `julasim/Blitztext`, Arbeitsbranch
`feat/meeting-mode`). Alles on-device.

**Fokus seit 2026-07-23: nur noch Dateien.** Diktat per Hotkey und
Live-Mitschnitt sind entfernt — die App fasst kein Mikrofon mehr an. Was
ausgebaut wird: Batch-Queue, Sprach-/Modellwahl beim Import,
Untertitel-Exports. Siehe „Offene Punkte".

## Status

**Architektur:**
- Shell ist Tauri 2 + React + TS (`app/`), der Python-Kern läuft als Sidecar
  (JSON-RPC 2.0 über ndjson/stdio, keine offenen Ports, SQLite gehört dem
  Sidecar). Begründung: High-Fidelity-Design braucht Web-Stack.
- **Installer: MSI/WiX** (entschieden 2026-07-23, `tauri.conf.json`).

**Zwei Rückbauten am 2026-07-23** — beides bleibt über die Git-Historie
erreichbar (`git checkout <commit> -- <pfad>`):
- **PyQt-Tray gelöscht.** Die ausgelieferte v1.0.25 liegt unverändert auf
  Branch `main`; die installierte Version unter `C:\Program Files\Blitztext\`
  läuft davon unberührt weiter.
- **Mikrofon-Funktionen gelöscht** (Diktat per Hotkey, Live-Mitschnitt,
  Mini-Widget). Entschieden, um die App auf Datei-Transkription zu
  fokussieren. Damit sind auch alle globalen Shortcuts weg — inklusive
  Strg+O, das als OS-weites Kürzel ohnehin fragwürdig war. Die App fordert
  kein Mikrofonrecht mehr an.

**`PLAN.md` ist teilweise überholt:** Phase 2 (Dictate-Migration,
System-Loopback, Settings-Unification) ist mit der Fokussierung hinfällig.
Phase 1 und die Architektur-Begründungen gelten weiter.

**Einzug in den Workspace (2026-07-14):**
- Von `Desktop\Blitztext` hierher verschoben (bewusst außerhalb OneDrive —
  Sync-Konflikte mit `node_modules`/`target`). Branding-`assets/` und
  `portable/`-Build mit eingezogen, `portable/` gitignored.
- Umzugsfolgen repariert und verifiziert: `.venv-sidecar` neu gebaut
  (Py 3.11.9, Torch 2.4.1+cu121, CUDA auf RTX 4060 bestätigt), Vite-Cache
  geleert; Sidecar-`ping`, `npm run build` und `cargo check` grün.

**Wiederaufnahme nach Ruhephase (2026-07-23):** Das Projekt lag seit 2026-04-29
still und hielt 40,1 GB Build-Artefakte. Diese wurden gelöscht (Details im
Änderungslog); die Entwicklungsumgebung ist wiederhergestellt und **verifiziert**:
`npm install` durch, `npm run build` grün (754 ms), Sidecar-`ping` antwortet
(`{"ok":true,"version":"0.1.0-alpha"}`), `cargo check` grün (24 s).
**`.venv-sidecar` blieb bewusst erhalten** — Neuaufbau kostet ~2,5 GB Download
plus CUDA-Verifikation.

## Offene Punkte / nächste Schritte

- **Vor dem nächsten Release-Build: Sidecar neu bauen.** `app/src-tauri/binaries/sidecar/`
  enthält aktuell nur `PLATZHALTER.txt` (der echte 4,8-GB-Build wurde beim Aufräumen
  gelöscht, war nie im Git). Die Datei muss dort liegen, sonst bricht schon
  `cargo check` mit „glob pattern binaries/sidecar/**/* … didn't match any files"
  ab — `tauri.conf.json` deklariert das als `resources`. **Für die Entwicklung
  genügt der Platzhalter**, weil `sidecar.rs` auf `cfg!(debug_assertions)` verzweigt
  und im Dev-Modus `python -m sidecar` aus `.venv-sidecar` startet.
  Echter Build: `.venv-sidecar\Scripts\python.exe -m PyInstaller build-sidecar.spec`,
  dann `dist\blitztext-sidecar\` → `app\src-tauri\binaries\sidecar\`.
- **Phase-1-Rest:** `speaker.sample` fehlt. Der Plan (Schritt 1 + 4.9) sieht beim
  Sprecher-Umbenennen ein **5-Sekunden-Audio-Snippet** vor, damit man hört, wen man
  gerade benennt. Rename und Merge sind in `SpeakerList.tsx` fertig, das Snippet
  nicht — es gibt weder die RPC-Methode in `sidecar/methods.py` noch ein
  `<audio>`-Element im Popover.
- **LRU-Deckel auf `_transcriber_cache`** (`meeting_pipeline.py`): wächst
  unbegrenzt, Schlüssel ist `modell:sprache:device`. Heute liegt genau ein
  Eintrag drin; sobald die UI Modelle wählen lässt, liegen `large-v3`,
  `turbo` und `medium` gleichzeitig im VRAM.
- **Danach:** Sprache/Modell/Diarization-Schalter im Import-UI (die Parameter
  existieren in `import_file` bereits, sie werden nur nicht durchgereicht) ·
  SRT/VTT/DOCX aus `words_json` · ID3-Tags für Titel und Datum (PyAV liefert
  sie mit, keine neue Dependency) · `meeting.reprocess` gegen die schon
  kopierte Datei.
- **Phase-1-Rest:** `speaker.sample` fehlt — beim Sprecher-Umbenennen soll
  man eine 5-Sekunden-Hörprobe hören. Rename und Merge sind in
  `SpeakerList.tsx` fertig, das Snippet nicht (weder RPC-Methode noch
  `<audio>`-Element). Bei fremden Aufnahmen wichtiger als bei eigenen.
- **`methods.py` aufteilen**, sobald das zweite Exportformat kommt: die
  Markdown-Formatierung gehört in ein `exporters/`-Modul, nicht neben die
  RPC-Wrapper.
- **Zwei Logdateien**: `core/log.py` schreibt `%APPDATA%\Blitztext\blitztext.log`,
  der Sidecar per stdlib-`logging` nach `sidecar.log`. Zusammenlegen wäre
  sinnvoll, ist aber eine eigene Aufgabe.

## Konventionen

- Sprache: Deutsch (Doku/Commits), Code/Bezeichner englisch.
- Sidecar-Contract: `sidecar/rpc_schema.md` ist Source of Truth — bei RPC-
  Änderungen zuerst dort pflegen (Stand 2026-07-23 vollständig abgeglichen;
  es war schon einmal drei Namensräume hinterher).
- venv-Installation immer mit CUDA-Index:
  `python3.11 -m venv .venv-sidecar` und
  `pip install -r sidecar\requirements.txt --index-url https://download.pytorch.org/whl/cu121 --extra-index-url https://pypi.org/simple`
  (kein `py`-Launcher auf dieser Maschine).

## Befehle

Alle Pfade relativ zum Projekt-Root (`apps/blitztext`). Python immer aus der
venv — es gibt kein aktiviertes Environment und keinen `py`-Launcher.

```powershell
# App im Dev-Modus (Vite + Rust + Sidecar aus .venv-sidecar)
cd app; npx tauri dev          # NICHT `npm run tauri` — dieses Script fehlt

# Frontend allein
cd app; npm run build          # tsc -b && vite build
cd app; npm run lint           # eslint (aktuell 4 Fehler, s. Stolpersteine)

# Rust allein (schnellster Syntax-/Typcheck der Shell)
cd app\src-tauri; cargo check

# Sidecar direkt sprechen (ndjson auf stdin) — Health-Check
'{"jsonrpc":"2.0","id":1,"method":"ping"}' | .\.venv-sidecar\Scripts\python.exe -m sidecar
```

**Tests** — pytest, Konfiguration in `pytest.ini`:

```powershell
.\.venv-sidecar\Scripts\python.exe -m pytest            # 36 Tests, ~1,5 s
.\.venv-sidecar\Scripts\python.exe -m pytest --slow     # + echte MP3 durch Whisper/pyannote
.\.venv-sidecar\Scripts\python.exe -m pytest --ollama   # + Cleanup gegen lokales Ollama
.\.venv-sidecar\Scripts\python.exe -m pytest -k merger  # einzelne Datei/Fall
```

Der Standardlauf ist absichtlich frei von Modellen, Ollama und Netz — teure
Tests tragen `@pytest.mark.slow` / `.ollama` und werden ohne die Flags
übersprungen (Mechanik in `tests/conftest.py`). Jeder Test bekommt über die
`store`-Fixture eine eigene DB unter einem Temp-`APPDATA`; die echte
Meeting-DB wird nie angefasst. Für Rust und TypeScript gibt es **keine**
Tests (Stand 2026-07-23).

**Release-Build:** Sidecar zuerst (`.venv-sidecar\Scripts\python.exe -m PyInstaller
build-sidecar.spec` → `dist\blitztext-sidecar\` nach `app\src-tauri\binaries\sidecar\`),
dann `cd app; npx tauri build` → MSI. Schritt für Schritt in `BUILD.md`.

**Eine Datei von der Kommandozeile transkribieren** (ohne GUI, volle Pipeline):

```powershell
.\.venv-sidecar\Scripts\python.exe transcribe.py "C:\pfad\meeting.mp3" --cleanup
```

---

## Der eine Datenpfad (wichtigste Architektur-Tatsache)

Zwischen Frontend und Python gibt es **genau einen** Kanal — wer eine Funktion
ergänzt, fasst immer dieselben vier Stellen an:

```
React  call("meeting.import_file", {...})        lib/rpc.ts
  → Tauri invoke("rpc", {method, params})        commands.rs — ein generisches Kommando, sonst nichts
  → SidecarHandle.call()                         sidecar.rs — ndjson auf stdin, Demux per id, 10-min-Timeout
  → serve_stdio → _dispatch → @method(...)       sidecar/rpc.py + methods.py
```

Rückweg für alles Langlaufende: die Methode startet einen Worker-Thread und
ruft `emit_event(name, payload)` → JSON-RPC-Notification ohne `id` → Rust
erkennt „kein id" und macht `app.emit("sidecar-event", …)` → im Frontend
`onEvent("meeting.progress", …)`. **Konsequenz:** RPC-Antworten kommen sofort
(z.B. nur die `meeting_id`), der eigentliche Fortschritt kommt als Event-Strom.

Rust ist bewusst dumm (~250 LOC Transport, null Domänenlogik). Neue Features
gehören nach Python; Rust nur anfassen für Fenster, Shortcuts, Prozess-Handling.

Was man über die Pipeline wissen muss:
- **Importe laufen durch die Warteschlange** (`sidecar/jobs.py`), nie direkt.
  `meeting.import_file` reiht nur ein und kehrt sofort zurück; ein einziger
  Worker-Thread arbeitet seriell ab. Zustand in der Tabelle `jobs`, damit ein
  Absturz nachvollziehbar bleibt.
- `meeting_pipeline.py` — fünf Stages (decode 5 % → transcribe 55 % →
  diarize 30 % → merge 5 % → persist 5 %), Gewichte stehen in `_STAGES` und
  ergeben die eine Prozentzahl der UI. Jeder Import läuft hier durch.
- Diarization ist **best effort**: fällt pyannote aus (Token, Lizenz, CUDA),
  läuft der Import mit leerer Segmentliste weiter → ein Sprecher, Split an
  langen Pausen, `meeting.warning`-Event statt Abbruch.
- Persistenz: SQLite unter `%APPDATA%\Blitztext\meetings.db` (3 Tabellen —
  `meetings`/`speakers`/`turns`, Sprecher-Statistiken denormalisiert), Audio je
  Meeting unter `%APPDATA%\Blitztext\meetings\<uuid>\`. Migrationen siehe
  `_MIGRATIONS` in `meeting_store.py`.

## Zentrale Bausteine

- `merge()` (`sidecar/merger.py`) — Word-Timestamps + Speaker-Segmente → Turns.
  Die anspruchsvollste Logik im Projekt.
- `run_stages()` (`sidecar/meeting_pipeline.py`) — die fünf Stages; jeder
  Import läuft hier durch.
- `JobQueue` (`sidecar/jobs.py`) — serielle Abarbeitung, Abbruch,
  Wiederanlauf. Einziger Ort, an dem die Pipeline gestartet wird.
- `Transcriber` (`core/transcription.py`) — faster-whisper-Wrapper.
- `_connect()` (`sidecar/meeting_store.py`) — SQLite-Zugang; einzige Verbindung,
  bewusst modulglobal (Single-Prozess-Modell).
- `cleanup_turn()` (`core/llm.py`) — einziger LLM-Aufruf im Produkt.
- `SidecarHandle` (`app/src-tauri/src/sidecar.rs`) — Rust-Seite: spawnt/verwaltet
  den Sidecar-Prozess, demultiplext Antworten per `id`.

## Datei-Landkarte

**Python-Kern** (`core/`): `transcription.py` (Whisper), `llm.py`
(Ollama-Cleanup), `log.py`. Mehr ist nicht drin.

**Sidecar** (`sidecar/` — das Backend):
- `rpc.py` + `methods.py` — JSON-RPC-Dispatcher + Methoden; Contract in
  `rpc_schema.md`.
- `jobs.py` — die Warteschlange (Worker-Thread, Zustände, Wiederanlauf).
- `meeting_pipeline.py`, `diarization.py`, `merger.py`, `meeting_store.py`,
  `audio_io.py` — die Pipeline (Datei → Whisper+pyannote → Turns → SQLite).

**Tests** (`tests/`, pytest): `conftest.py` (isolierte DB je Test, Opt-in-Flags),
`test_merger.py`, `test_store.py`, `test_migrations.py`, `test_export.py`,
`test_rpc.py`, `test_jobs.py`; markiert und übersprungen:
`test_pipeline_mp3.py` (`--slow`), `test_cleanup.py` (`--ollama`).

**Tauri-App** (`app/`):
- `src/` — React: `App.tsx`, Views (`MeetingImport`, `MeetingReview`,
  `Library`, `Settings`), Store `state/useMeetingStore.ts`, RPC-Client
  `lib/rpc.ts`, Typ-Spiegel `lib/types.ts`.
- `src-tauri/` — Rust-Shell: `lib.rs` (Fenster + Sidecar-Start), `sidecar.rs`,
  `commands.rs`, `capabilities/` (Permissions), `tauri.conf.json`.
  Ein Fenster, keine globalen Shortcuts.

**Werkzeug & Doku:**
- `transcribe.py` — CLI: eine Audiodatei durch die volle Pipeline → Markdown.
  Einziger Batch-Einstieg, den es heute gibt.
- `BUILD.md` — Release (PyInstaller-Sidecar + Tauri-MSI); `build-sidecar.spec`.
- `PLAN.md` — Umbau-Roadmap (Phase 0–3). Öffnen bei jeder Architekturfrage.
- `assets/` — Branding-SVGs.

## Stolpersteine

- **venv nach Ordner-Umzug immer neu bauen** (absolute Pfade eingebacken);
  Install-Befehl siehe Konventionen.
- **`binaries/sidecar/` darf nie leer sein** — sonst scheitert jeder Rust-Build
  (auch `cargo check`) am Resource-Glob aus `tauri.conf.json`, mit einer Meldung,
  die nach einem Config-Fehler aussieht, aber nur ein fehlender Ordner ist.
- **`npm run tauri dev` gibt es nicht** — `app/package.json` hat nur
  `dev`/`build`/`lint`/`preview`. Richtig ist `npx tauri dev`.
- **`matplotlib` in `sidecar/requirements.txt` sieht wie eine Plot-Leiche aus
  und ist keine**: pyannote importiert es auf Modulebene
  (`pyannote/audio/tasks/segmentation/speaker_diarization.py`, `mixins.py`),
  kein Paket deklariert es als Dependency. Rausnehmen killt die Diarization.
  Steht mit Begründung in den requirements — Kommentar nicht wegkürzen.
- **`pct` in `meeting.progress` ist 0..1**, nicht 0..100 — trotz des Namens.
- **`created_at` hat nur Sekunden-Auflösung** (`_now_iso`). Deshalb sortiert
  `list_meetings` mit `created_at DESC, rowid DESC` — beim Stapel-Import fällt
  sonst alles in dieselbe Sekunde und die Reihenfolge wird beliebig. Wer eine
  neue Abfrage nach Zeit schreibt, braucht denselben zweiten Schlüssel.
- **Schema-Änderung = neue Migration.** `meeting_store._MIGRATIONS` ist eine
  Liste nummerierter SQL-Schritte gegen `PRAGMA user_version`, forward-only.
  Anleitung steht im Kommentar darüber; alte Schritte nie ändern.
- **Diarization läuft absichtlich auf der CPU.** `BLITZTEXT_DIAR_CPU` steht per
  Default auf `1` (`sidecar/diarization.py:121`): torch+cu121 bringt unter
  Windows ein cuDNN mit fehlendem Symbol mit, das pyannote-Inferenz aus
  nativem Code heraus killt — unfangbar für Python. Whisper behält die GPU.
  `device = cpu` beim Laden ist also **kein** Defekt.
- **Abbruch greift nicht während der Diarization.** Prüfpunkte gibt es an den
  Stage-Grenzen und nach jedem Whisper-Segment; pyannote meldet keinen
  Fortschritt, also wartet ein Abbruch dort, bis sie fertig ist. Bewusst so
  belassen — ein Knopf, der lügt, wäre schlimmer als einer, der wartet.
- **Ein `running`-Job beim Start = Absturz.** Nur ein Prozess besitzt die DB.
  `JobQueue.recover_orphans()` reiht solche Jobs neu ein, höchstens
  `MAX_ATTEMPTS` (2) mal — sonst dreht eine Datei, die den Prozess
  zuverlässig killt, eine Endlosschleife über alle Neustarts.
- **`jobs.meeting_id` ist NULL-bar** (`ON DELETE SET NULL`). Beim Abbruch
  verschwindet die leere Meeting-Hülle, der Job-Eintrag bleibt als Historie.
  Wer über Jobs joint, muss NULL abfangen.
- pyannote braucht HF-Account mit akzeptierten Modell-Lizenzen (`PLAN.md` § Phase 0).
  Token liegt im Windows-Anmeldeinformationsmanager (`keyring`, Dienst
  `Blitztext`, Key `hf_token`) — prüfbar über die RPC-Methode
  `settings.test_hf_token` (unterscheidet auth-ok von gated-Zugriff fehlt).
- Pinned Deps nicht „aufräumen": `huggingface_hub<0.30` und `speechbrain<1.1`
  sind bewusst gepinnt (Runtime-Konflikte mit pyannote 3.3.x, siehe
  `sidecar/requirements.txt`).

---

## Änderungslog

- 2026-07-23 — **Stapel-Import sichtbar gemacht.** `queue.enqueue` nimmt
  Dateien **und Ordner** (rekursiv, alphabetisch, mit `skipped`-Begründung je
  aussortiertem Pfad); die Endungsliste steht einmal in `audio_io` und kommt
  über `config.get` ins Frontend, damit der Dateidialog keine zweite pflegt.
  Import-View auf Mehrfachauswahl, Ordnerwahl und Mehrfach-Drop umgebaut, neue
  `QueuePanel` in der Seitenleiste (laufender Job mit Stage und Balken,
  Wartende nummeriert, Fehlgeschlagene mit Grund, jeweils abbrechbar). Der
  Store lädt die Liste bei jedem `queue.*`-Event neu, statt lokal
  mitzuzählen — bei Abbruch und Wiederanlauf liefe das sonst auseinander.
  9 neue Tests für die Pfad-Auflösung.
- 2026-07-23 — **Import-Warteschlange** (`sidecar/jobs.py`, Migration 2).
  Ersetzt das Thread-pro-Aufruf-Modell: ein Worker arbeitet seriell ab, der
  Zustand liegt in der Tabelle `jobs`. Damit gibt es erstmals **Abbruch**
  (wartend sofort, laufend am nächsten Prüfpunkt) und **Wiederanlauf** —
  ein Job, der beim Start auf `running` steht, kann nur ein Absturz sein und
  geht zurück in die Schlange, höchstens zweimal. Ein fehlgeschlagener Job
  stoppt die Schlange nicht. `meeting.import_file` reiht jetzt nur noch ein
  (gibt zusätzlich `job_id` zurück), dazu `queue.list/state/cancel/
  clear_finished` und sieben `queue.*`-Events. 17 neue Tests gegen eine
  eingesetzte Pipeline plus ein `--slow`-Integrationstest mit zwei echten
  MP3s. Bewusste Grenze: während der Diarization gibt es keinen
  Abbruch-Prüfpunkt, weil pyannote keinen Fortschritt meldet.
- 2026-07-23 — **Fokus: nur noch Datei-Transkription.** Entscheidung von
  Julius, radikale Variante. Entfernt: `sidecar/dictate.py`,
  `sidecar/recording.py`, `core/audio.py`, `core/injector.py`,
  `MiniWidget.tsx`, das Mini-Fenster, alle globalen Shortcuts samt
  `tauri-plugin-global-shortcut`, die elf `recording.*`/`dictate.*`-RPCs und
  die Deps `sounddevice`/`pyautogui`/`pyperclip`. Die App fordert **kein
  Mikrofonrecht** mehr an. UI-Texte nachgezogen („Meeting Mode" →
  „Transkription", „Neues Meeting" → „Datei transkribieren", „Aufnahmen" →
  „Transkripte"). Verifiziert: 36 Tests, Lint, Build, `cargo check`,
  Sidecar-`ping` — alle grün.
- 2026-07-23 — **Fundament für den Ausbau: pytest + echte Migrationen**
  (`db3160e`). 36 Tests in ~1 s ohne Modelle/Ollama/Netz, teure Läufe hinter
  `--slow`/`--ollama`; `_MIGRATIONS` gleicht `PRAGMA user_version` ab, statt
  ihn nur zu stempeln. Zwei Fehler dabei gefunden: `list_meetings` war bei
  gleichem `created_at` beliebig sortiert (jetzt `rowid DESC` als zweiter
  Schlüssel), und `_smoke_e2e` prüfte ein Feld, das `cleanup.run` seit der
  Async-Umstellung nicht mehr zurückgibt — der Test wäre immer durchgefallen,
  wurde aber nie gestartet.
- 2026-07-23 — **Große Aufräumrunde in fünf Stufen** (vier Commits, `7a3babe`
  bis Doku). Anlass: das Repo trug zwei Produkte parallel, bevor die
  Spezialisierung auf MP3-Transkription beginnt.
  (1) **PyQt-Tray gelöscht** — `main.py`, `ui/`, sieben `core/`-Module,
  `config/`, `requirements.txt`, `build.spec`, `installer/`, `models/`;
  `core/llm.py` von 343 auf ~130 Zeilen (die fünf Cloud-Provider hingen nur am
  Tray). v1.0.25 bleibt auf `main`.
  (2) **Tote Deps:** `librosa` (nichts importiert es — PyAV kommt mit
  faster-whisper), `keyboard`, `@tanstack/react-virtual`, `plugin-shell`,
  `plugin-global-shortcut`, `plugin-fs` (JS + Rust + Capabilities), doppelte
  `@fontsource`-Imports.
  (3) **Artefakte:** vier `__pycache__` (darunter 27 `.cpython-314.pyc` aus der
  Legacy-Ära), leere Ordner. `assets/` und `binaries/sidecar/PLATZHALTER.txt`
  neu getrackt.
  (4) **Lint von 4 Fehlern auf grün** — `withoutKey()`-Helfer statt zweimal
  `_drop`, Lazy-Initializer und entzerrtes Dep-Array in `MiniWidget`,
  Mount-Fetch mit cancelled-Guard in `Settings`, tote `Dropzone`-Props,
  doppelter (statisch + dynamisch) `rpc.ts`-Import in `App.tsx`.
  (5) **Doku:** `rpc_schema.md` komplett gegen `methods.py` neu geschrieben
  (drei fehlende Namensräume, `cleanup.turn_done` existierte nie, `pct` ist
  0..1), `BUILD.md` auf Sidecar+MSI umgestellt, `README.md`, `PLAN.md`-Pfade,
  `types.ts` (`status: "recording"` fehlte).
  Verifiziert: Sidecar-`ping` inkl. pyannote-Preload, `_smoke_merger`,
  `_smoke_store`, `npm run build`, `npm run lint`, `cargo check` — alle grün.
- 2026-07-23 — **Voll-Analyse vor dem Ausbau; diese Datei um Befehle und
  Datenpfad erweitert.** Neu: Abschnitt „Befehle" (Dev/Build/Lint/Smoke-Tests/
  Release, alle mit venv-Pfad) und „Der eine Datenpfad" (React → invoke →
  `sidecar.rs` → `@method`, Rückweg über `emit_event`/`sidecar-event`).
  **Gemessen, nicht vermutet:** `_smoke_merger` und `_smoke_store` laufen grün;
  `npm run lint` ist rot (4 Fehler / 2 Warnungen, Altbestand); es gibt weder
  Rust- noch TS-Tests. **Drei Doku-Fehler gefunden:** `rpc_schema.md` kennt
  `recording.*`/`dictate.*`/`settings.*` nicht und markiert fertige Methoden als
  Stub; `README.md` nennt `npm run tauri dev`, das Script existiert nicht;
  `sidecar.rs` meldet 30 s Timeout statt 600 s.
- 2026-07-23 — **Entrümpelt (40,1 → 5,2 GB) und Dev-Umgebung wiederhergestellt.**
  Gelöscht (alles gitignored, regenerierbar, kein getrackter Inhalt berührt):
  `app/src-tauri/target` (19,6 GB), `app/src-tauri/binaries` (4,8 GB),
  `portable/`, `dist/`, `dist-installer/`, `build/`, `app/node_modules`,
  `__pycache__/`, `.claude/graph/venv`. **Behalten:** `.venv-sidecar` (5,3 GB).
  Danach wiederhergestellt und verifiziert: `npm install`, `npm run build` (grün),
  Sidecar-`ping` (grün), `cargo check` (grün, 24 s nach Voll-Rebuild).
  **Dabei gelernt:** der fehlende `binaries/`-Ordner bricht `cargo check` sofort —
  der Resource-Glob in `tauri.conf.json` muss matchen, unabhängig vom Build-Profil.
  Deshalb liegt dort jetzt `PLATZHALTER.txt` (siehe „Offene Punkte").
- 2026-07-14 — Einzug von `Desktop\Blitztext` nach `apps/blitztext`; Umzugsfolgen
  repariert (venv neu, CUDA verifiziert, Builds grün); CLAUDE.md aufs
  Kontext-Primer-Format gehoben (graphify-gemessene Bausteine/Landkarte).
