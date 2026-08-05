<!--
ANWEISUNG AN CLAUDE: Diese Datei zuerst lesen, um den Ordner zu verstehen.
Bevor du die Arbeit in diesem Ordner beendest: diese Datei aktualisieren —
neue Entscheidungen in den Status, erledigte Punkte aus "Offene Punkte"
entfernen, neue Dateien in die Landkarte, "Zuletzt aktualisiert" + Änderungslog
pflegen. Stufe 1 reicht meist; Stufe 2 nur lesen, wenn die Aufgabe es verlangt.
-->

# Blitztext

Zuletzt aktualisiert: 2026-08-05 · Version 0.2.0

## Worum geht's

**Transkribiert Audiodateien lokal** (MP3, WAV, M4A, FLAC, OGG) auf Windows:
Import → Whisper oder Parakeet → Sprecher-Trennung → Review → LLM-Cleanup →
Export. Dateien und ganze Ordner laufen als Warteschlange durch, seriell und
abbrechbar. Eigenes Produkt von Julius (GitHub `julasim/Blitztext`,
Arbeitsbranch `feat/meeting-mode`). Alles on-device.

**Fokus seit 2026-07-23: nur noch Dateien.** Diktat per Hotkey und
Live-Mitschnitt sind entfernt — die App fasst kein Mikrofon mehr an. Was
ausgebaut wird: Batch-Queue, Sprach-/Modellwahl beim Import,
Untertitel-Exports. Siehe „Offene Punkte".

## Grundsatz: ausschließlich lokale Modelle

**Transkribiert wird nur mit Modellen, die auf dem Rechner laufen.** Es gibt
keinen Zugang zu Cloud-Modellen und soll keinen geben.

- **Whisper** (`faster-whisper`) — lokal, GPU oder CPU.
- **pyannote 4 / community-1** — lokal, GPU (seit torch 2.8; Details in
  den Stolpersteinen).
- **Ollama** für den Cleanup — `127.0.0.1:11434`, also Loopback.

Der Code enthält **keine API-Keys, keinen Inferenz-Endpunkt, keine
Telemetrie**. Achtung dabei: **pyannote 4 bringt eigene Opt-out-Telemetrie
mit, per Default AN** (`otel.pyannote.ai`, plus mitinstalliertem
`pyannoteai-sdk`). `sidecar/diarization.py` setzt
`PYANNOTE_METRICS_ENABLED=false`, **bevor** pyannote importiert wird — beim
Anfassen dieser Stelle nicht hinter den Import rutschen lassen. Die fünf Cloud-Provider (OpenAI, Anthropic, Gemini, OpenRouter,
Ollama-Cloud) hingen am PyQt-Tray und sind am 2026-07-23 mit ihm gelöscht
worden; `core/llm.py` kennt nur noch `_call_ollama_local`.

Ausgehende Verbindungen gibt es an genau zwei Stellen, beide **einmalige
Modell-Downloads**, danach läuft alles offline:

1. `core/transcription.py` → `huggingface.co`, lädt die Whisper-Gewichte nach
   `%APPDATA%\Blitztext\models` (bzw. `BLITZTEXT_MODELS_DIR`).
2. `huggingface_hub` (über pyannote) → das Diarization-Modell
   `speaker-diarization-community-1`. Gated, deshalb der HF-Token; die
   Bedingungen des Repos müssen auf HF akzeptiert sein (erledigt
   2026-07-24). `settings.test_hf_token` prüft beide Repos auf Knopfdruck.

Wer eine Cloud-Anbindung ergänzen will, ändert damit den Produktkern —
das ist keine Implementierungsdetail-Entscheidung.

## Status

**Architektur:**
- Shell ist Tauri 2 + React + TS (`app/`), der Python-Kern läuft als Sidecar
  (JSON-RPC 2.0 über ndjson/stdio, keine offenen Ports, SQLite gehört dem
  Sidecar). Begründung: High-Fidelity-Design braucht Web-Stack.
- **Auslieferung: portabler Ordner**, kein Installer (entschieden
  2026-08-05). MSI scheitert hart an der Größe — das CAB-Format hinter MSI
  kann keine 2 GB pro Paket, der Sidecar ist 4,7 GB. `make-portable.ps1`
  stellt das Paket zusammen, verteilt wird über den NAS.

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

- **`speaker.sample` fehlt.** Der Plan (Schritt 1 + 4.9) sieht beim
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
  `.venv-sidecar\Scripts\python.exe -m pip install -r sidecar\requirements.txt --index-url https://download.pytorch.org/whl/cu128 --extra-index-url https://pypi.org/simple`
  (kein `py`-Launcher auf dieser Maschine; immer `python -m pip`, nie die
  EXE-Shims — die überleben kein Verschieben der venv).

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
.\.venv-sidecar\Scripts\python.exe -m pytest            # 133 Tests, ~10 s
.\.venv-sidecar\Scripts\python.exe -m pytest --slow     # + echte MP3 durch Whisper/pyannote
.\.venv-sidecar\Scripts\python.exe -m pytest --ollama   # + Cleanup gegen lokales Ollama
.\.venv-sidecar\Scripts\python.exe -m pytest -k merger  # einzelne Datei/Fall
```

Der Standardlauf ist absichtlich frei von Modellen, Ollama und Netz — teure
Tests tragen `@pytest.mark.slow` / `.ollama` und werden ohne die Flags
übersprungen (Mechanik in `tests/conftest.py`). Jeder Test bekommt über die
`store`-Fixture eine eigene DB unter einem Temp-`APPDATA`; die echte
Meeting-DB wird nie angefasst. Für Rust und TypeScript gibt es **keine**
Tests.

**Release** — drei Schritte, Details in `BUILD.md`:

```powershell
.\.venv-sidecar\Scripts\python.exe -m PyInstaller build-sidecar.spec --noconfirm
Copy-Item -Recurse -Force dist\blitztext-sidecar\* app\src-tauri\binaries\sidecar\
cd app; npx tauri build --no-bundle; cd ..
.\make-portable.ps1        # → release\Blitztext-<version>-portable\
```

**Eine Datei von der Kommandozeile transkribieren** (ohne GUI, volle Pipeline):

```powershell
.\.venv-sidecar\Scripts\python.exe transcribe.py "C:\pfad\meeting.mp3" `
  --vocabulary "ÖNORM, Bewehrung" --cleanup --cleanup-mode readable
```

**Qualität messen** (`benchmark/`, Details in `benchmark/README.md`):

```powershell
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --selftest       # ohne eigenes Material
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --prepare <audio> # Referenz-Gerüst
.\.venv-sidecar\Scripts\python.exe benchmark\run.py --label baseline   # messen
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

**Python-Kern** (`core/`): `transcription.py` (Whisper), `parakeet.py`
(Parakeet über ONNX, Token→Wort + Fenster-Naht), `llm.py` (Ollama-Cleanup),
`log.py`. Mehr ist nicht drin.

**Sidecar** (`sidecar/` — das Backend):
- `rpc.py` + `methods.py` — JSON-RPC-Dispatcher + Methoden; Contract in
  `rpc_schema.md`.
- `jobs.py` — die Warteschlange (Worker-Thread, Zustände, Wiederanlauf).
- `meeting_pipeline.py`, `diarization.py`, `merger.py`, `meeting_store.py`,
  `audio_io.py` — die Pipeline (Datei → Whisper+pyannote → Turns → SQLite).

**Tests** (`tests/`, pytest): `conftest.py` (isolierte DB und Queue je Test,
Opt-in-Flags), `test_merger.py`, `test_store.py`, `test_migrations.py`,
`test_export.py`, `test_rpc.py`, `test_jobs.py`, `test_audio_io.py`,
`test_vocabulary.py`, `test_parakeet.py`, `test_benchmark.py`; markiert und
übersprungen: `test_pipeline_mp3.py` (`--slow`), `test_cleanup.py`
(`--ollama`).

**Tauri-App** (`app/`):
- `src/` — React: `App.tsx`, Views (`MeetingImport`, `MeetingReview`,
  `Library`, `Settings`), Store `state/useMeetingStore.ts`, RPC-Client
  `lib/rpc.ts`, Typ-Spiegel `lib/types.ts`.
- `src-tauri/` — Rust-Shell: `lib.rs` (Fenster + Sidecar-Start), `sidecar.rs`,
  `commands.rs`, `capabilities/` (Permissions), `tauri.conf.json`.
  Ein Fenster, keine globalen Shortcuts.

**Werkzeug & Doku:**
- `benchmark/` — Messaufbau: WER, Schleifen-Anteil und Sprecheranzahl gegen
  korrigierte Referenzen. `run.py` (CLI), `metrics.py`, `reference.py`, dazu
  `make_testset.py` + `winrt_tts.ps1`, die den synthetischen Testsatz aus den
  Windows-Stimmen erzeugen. Nicht im Paket. `data/`, `results/`, `.work/`
  sind gitignored — dort liegen echte Bauberatungen.
- `transcribe.py` — CLI: eine Audiodatei durch die volle Pipeline → Markdown,
  mit `--vocabulary`, `--cleanup` und `--cleanup-mode`.
- `BUILD.md` — Release Schritt für Schritt; `build-sidecar.spec` (PyInstaller,
  filtert 2,7 GB Nicht-Laufzeit-Ballast aus torch), `make-portable.ps1`
  (stellt das verteilbare Paket zusammen; **muss UTF-8 mit BOM bleiben**,
  sonst liest PowerShell 5.1 es als ANSI und stolpert über den ersten
  Gedankenstrich).
- `PLAN.md` — **historisch**, Stand April 2026: nennt gelöschte Dateien
  (`main.py`, `core/audio.py`, `librosa`) und die hinfällige Phase 2. Für die
  Architektur-Begründungen weiter nützlich, nicht als Aufgabenliste lesen.
- `assets/` — Branding-SVGs.

## Stolpersteine

- **venv nach Ordner-Umzug immer neu bauen** (absolute Pfade eingebacken);
  Install-Befehl siehe Konventionen.
- **`binaries/sidecar/` darf nie leer sein** — sonst scheitert jeder Rust-Build
  (auch `cargo check`) am Resource-Glob aus `tauri.conf.json`, mit einer Meldung,
  die nach einem Config-Fehler aussieht, aber nur ein fehlender Ordner ist.
- **`npm run tauri dev` gibt es nicht** — `app/package.json` hat nur
  `dev`/`build`/`lint`/`preview`. Richtig ist `npx tauri dev`.
- **`condition_on_previous_text` steht bewusst auf `False`.** Es speist
  Whispers eigene Ausgabe als Prompt ins nächste 30-Sekunden-Fenster; bei
  Raummikrofon und Kreuzreden schaukeln sich daraus Wiederholungsschleifen
  auf. Auf echtem Material gemessen (PPSV-Besprechung): 1,7 % der Wörter in
  Schleifen mit `True`, 1,1 % mit `False` — und im Lauf mit Vokabular
  35× „servus" hintereinander. Wer es zurückstellt, misst vorher mit
  `benchmark/metrics.find_loops`.
- **Entrauschen mit DeepFilterNet3 wurde geprüft und verworfen** (2026-07-27).
  Die Literatur verspricht 20–40 % relative WER-Verbesserung bei verrauschtem
  Audio; auf der PPSV-Besprechung (Raummikrofon, mehrere entfernte Sprecher,
  Hall) war das Ergebnis **schlechter**: bei voller Dämpfung fiel der RMS um
  96 % und Whisper produzierte Wortsalat („Der Fickdorfer lernt" statt „Dann
  bauen wir es"), bei begrenzter Dämpfung (6/12 dB) stiegen die
  Wiederholungsschleifen. Grund: das Modell ist auf Nahsprech-Audio trainiert
  und hält Raumhall für Rauschen — es dämpft genau die leisen, entfernten
  Sprecher weg, die man am dringendsten bräuchte. Nicht erneut versuchen ohne
  Material aus Nahmikrofonen. Nebenbei: `deepfilternet` fordert `numpy<2.0`,
  pyannote 4 fordert `>=2.2` — der Pin ist veraltet (läuft auch mit numpy 2),
  aber pip meldet bei jeder Installation einen Konflikt.
- **Fachvokabular kann schaden.** `hotwords` wirkt bei jedem Fenster und
  verschiebt die Ausgabe bei schwierigem Audio massiv — im Test stieg der
  Schleifenanteil von 1,7 auf 5,2 %. Personennamen sind riskant (fallen in
  Begrüßungspassagen, wo ohnehin alle durcheinanderreden), Normbegriffe
  sind sicher. Sparsam halten und messen.
- **`pct` in `meeting.progress` ist 0..1**, nicht 0..100 — trotz des Namens.
- **`created_at` hat nur Sekunden-Auflösung** (`_now_iso`). Deshalb sortiert
  `list_meetings` mit `created_at DESC, rowid DESC` — beim Stapel-Import fällt
  sonst alles in dieselbe Sekunde und die Reihenfolge wird beliebig. Wer eine
  neue Abfrage nach Zeit schreibt, braucht denselben zweiten Schlüssel.
- **Schema-Änderung = neue Migration.** `meeting_store._MIGRATIONS` ist eine
  Liste nummerierter SQL-Schritte gegen `PRAGMA user_version`, forward-only.
  Anleitung steht im Kommentar darüber; alte Schritte nie ändern.
- **Diarization-Gerät ist versionsgekoppelt** (`sidecar/diarization.py`):
  unter pyannote 3.x/torch 2.4 erzwingt der Default CPU (cuDNN-Symbolfehler
  killt die Inferenz aus nativem Code, unfangbar); unter pyannote 4/torch 2.8
  ist der Fehler behoben (verifiziert 2026-07-24, 31 s Audio in 1,9 s auf der
  4060) und der Default ist GPU. `BLITZTEXT_DIAR_CPU` überstimmt beide.
- **Die torchcodec-Warnung beim pyannote-4-Import ist harmlos und laut.**
  torchcodec findet ohne System-FFmpeg seine DLLs nicht; pyannote bräuchte es
  nur für Datei-I/O. Wir übergeben In-Memory-Tensoren — exakt der von der
  Warnung selbst empfohlene Weg. Nicht „reparieren", nicht ffmpeg
  installieren.
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
- pyannote braucht einen HF-Account, der die Bedingungen von
  `pyannote/speaker-diarization-community-1` akzeptiert hat. Token liegt im
  Windows-Anmeldeinformationsmanager (`keyring`, Dienst `Blitztext`, Key
  `hf_token`) — prüfbar über `settings.test_hf_token` (unterscheidet
  auth-ok von „gated-Zugriff fehlt").
- **Die alten Pins `huggingface_hub<0.30` und `speechbrain<1.1` sind seit
  pyannote 4 weg** und dürfen nicht zurück — speechbrain ist gar nicht mehr
  installiert. Begründung steht in `sidecar/requirements.txt`.
- **Nur function-local importierte Module gehören in `build-sidecar.spec`.**
  PyInstaller sieht sie beim Bytecode-Scan nicht; Pakete mit Datendateien
  (`onnx_asr` → NeMo-Preprocessor-Gewichte) brauchen zusätzlich
  `collect_all`. Sonst läuft der Dev-Build und der Installer bricht auf der
  Zielmaschine ab.

---

## Änderungslog

- 2026-08-05 — **Version 0.2.0 gebaut und als portabler Ordner
  ausgeliefert** (`release\Blitztext-0.2.0-portable\`, 4,72 GB).
  **MSI ist strukturell gescheitert**, nicht an einer Einstellung: das
  CAB-Format hinter MSI kann keine 2 GB pro Paket, `light.exe` bricht ab.
  Entscheidung: portabler Ordner, über den NAS verteilbar, keine
  Registry-Spuren. `tauri.conf.json` behält `nsis` als Ziel für den Tag,
  an dem der Sidecar klein genug ist.
  **2,7 GB Ballast gefunden:** `collect_all("torch")` nimmt auch die Teile
  mit, die nur zum *Kompilieren gegen* torch gebraucht werden — statische
  Bibliotheken (`dnnl.lib` allein 2,2 GB), C++-Header, Typ-Stubs. Die Spec
  filtert sie jetzt heraus: 9532 Dateien, 7,4 → 4,71 GB, ohne Funktionsverlust.
  **Am gepackten Sidecar verifiziert**, nicht am Import: beide ASR-Modelle
  transkribieren wirklich (Parakeet 36 s inkl. Laden, Whisper 2 s) — damit
  ist der `onnx_asr`-Fix belegt. Die portable EXE startet, findet ihren
  Sidecar über `resource_dir()` und fährt die Pipeline hoch; im Log dabei
  der Wiederanlauf im echten Betrieb.
  Dabei ein eigener Fehler: der Test lief ohne isoliertes `APPDATA` und
  schrieb drei Läufe in die produktive Meeting-DB — entfernt.

- 2026-07-27 — **Aufräumrunde mit drei Prüf-Agenten** (Python, Frontend/Rust,
  Ordner/Dependencies). Sie haben **drei echte Fehler** gefunden, die keine
  Kosmetik waren:
  1. **`--cleanup` in `transcribe.py` war kaputt.** Der Aufruf ging über die
     inzwischen asynchrone `cleanup.run`, las ein `processed`-Feld, das es
     nicht mehr gibt (KeyError, vom generischen `except` geschluckt), und
     der Export schrieb los, während der Worker noch lief. Jetzt direkt über
     `cleanup_turn`, Turn für Turn, mit Fortschrittsanzeige.
  2. **`build-sidecar.spec` hätte den nächsten Installer zerstört.**
     `onnx_asr` fehlte in `collect_all` — Parakeet wäre erst auf der
     Zielmaschine abgebrochen, weil die NeMo-Preprocessor-Gewichte
     (`nemo80.onnx` u.a.) nicht mitgepackt worden wären. Dazu fehlten
     `core.parakeet` und `sidecar.jobs` in `hiddenimports`, und
     `transformers` stand dort, obwohl es gar nicht installiert ist.
  3. **Der Benchmark protokollierte das falsche Gerät.** `environment()`
     riet `"cpu"` aus einem Default, der seit pyannote 4 nicht mehr gilt —
     jede Ergebnisdatei behauptete CPU-Diarization, obwohl auf der GPU
     gerechnet wurde. Fragt jetzt die Pipeline selbst.
  Dazu zwei **Widerlegungen meiner eigenen Vorgaben**: `whisper_models` wird
  vom Frontend nicht mehr gelesen (Settings.tsx liest seit Parakeet
  `config.models`), und `matplotlib` ist unter pyannote 4 eine deklarierte
  Dependency — der Sonderfall aus der 3.x-Zeit ist weg, der Eintrag konnte
  raus. Entfernt außerdem: `dialog:allow-ask`/`-message` (nie aufgerufen),
  `core:window:allow-is-maximized` (schon in `core:default`),
  `python_executable`/`whisper_default`/`ollama_default` aus den
  RPC-Antworten, sieben ungenutzte CSS-Tokens, `DIAR_MODEL`,
  `_row_to_dict`, ein totes Regex, zwei `#[allow(...)]` in Rust, ein
  doppelter CSS-Import. Artefakte: 3 MB Graphify-Index von **vor** beiden
  Rückbauten (verwies noch auf `main.py`, `MiniWidget.tsx`), 125 MB
  Benchmark-Scratch, vier `.pyc` gelöschter Module.
  Nutzersichtbar korrigiert: die Einstellungen nannten noch
  `speaker-diarization-3.1` als zu akzeptierende Lizenz statt
  `community-1` — wer der Anleitung folgte, bekam trotzdem einen
  Gated-Fehler.

- 2026-07-27 — **Sauberere Transkripte, und ein Fund, der die Richtung
  korrigiert hat.** Umgesetzt: satzbewusster Merger (`normalize_word_spacing`,
  `sentence_grace_ms`, `bridge_interjection_ms`), Fachvokabular über
  `hotwords` aus zwei Quellen (Firmenliste in Migration 3 + Feld beim
  Import), zweistufiger Cleanup (`faithful`/`readable`, Idempotenz je Stufe
  über `turns.text_clean_mode`).
  **Dann die Messung am echten Material:** das Vokabular hat den Anteil
  halluzinierter Wiederholungen von 1,7 auf **5,2 %** getrieben (35× „servus"
  am Stück). Ursache war nicht das Vokabular selbst, sondern
  `condition_on_previous_text=True` — jetzt `False`, dazu
  `hallucination_silence_threshold=2.0`. Ergebnis: Schleifen auf 1,1 %,
  Laufzeit der 18-Minuten-Datei von 198 auf 125 s.
  Neu im Messaufbau: `find_loops` — die erste Qualitätszahl, die **ohne
  korrigierte Referenz** trägt.

- 2026-07-24 — **Parakeet TDT v3 als zweites ASR-Modell** (`core/parakeet.py`
  über `onnx-asr`, bewusst CPU/ONNX — kein onnxruntime-gpu neben torch).
  Auf dem Testsatz **genauer als Whisper large-v3** (mittleres WER 0,8 %
  gegen 2,3 %; Fachbegriffe 2,3 % gegen 6,8 %) bei ~600 MB statt 3 GB.
  Token→Wort-Konversion und 240-s-Fenster-Naht als reine, getestete
  Funktionen. Engine-Dispatch über den Modellnamen in
  `meeting_pipeline._get_transcriber`; `config.get` liefert `models`
  ({id, label, hint}), der Import-View hat eine Modellwahl (Default
  Automatik). Benchmark-Fund: ONNX optimiert beim ersten Aufruf —
  `warm_up` schiebt jetzt 1 s Stille durchs Modell, sonst misst die erste
  Datei 30 s statt 4 s. **Phase 3 (Cleanup-Modell) blockiert:** Ollama ist
  auf dieser Maschine nicht installiert; erst installieren + Kandidaten
  per `pytest --ollama` messen, dann `OLLAMA_LOCAL_DEFAULT_MODEL` anfassen.
- 2026-07-24 — **Stack-Umstieg: torch 2.8+cu128 / pyannote 4.0.7 /
  community-1.** Über parallele venv gemessen, dann umgeschaltet (Neuaufbau
  aus dem pip-Cache statt Rename — EXE-Shims betten absolute Pfade ein).
  Messung auf dem synthetischen Testsatz: WER und Sprecherzahl identisch
  zur Baseline, Laufzeit **2,6–5× schneller**, weil der cuDNN-Fehler von
  cu121 behoben ist und die **Diarization wieder auf der GPU** läuft
  (31 s Audio in 1,9 s). Geräteswahl jetzt versionsgekoppelt. Drei Funde:
  pyannote 4 bringt **Opt-out-Telemetrie, Default AN** (otel.pyannote.ai) —
  abgeschaltet via `PYANNOTE_METRICS_ENABLED=false` vor dem Import;
  speechbrain ist komplett entfallen (keine lazy Imports, Pin gestrichen);
  die laute torchcodec-Warnung ist harmlos (wir übergeben In-Memory-
  Tensoren). `.venv-sidecar-old` (torch 2.4) bleibt als Rückfall, bis
  echtes Material gemessen ist. `settings.test_hf_token` probt beide
  gated Repos.
- 2026-07-24 — **Messaufbau `benchmark/`.** Anlass: die Recherche zeigt
  bessere Modelle (Qwen3-ASR, pyannote 4/community-1), aber alle Zahlen
  stammen aus englischen Benchmarks — und pyannote 4 verlangt **torch ≥ 2.8**
  gegen unsere 2.4.1+cu121. Ein Upgrade dieser Größe blind zu machen wäre
  falsch, also erst messen. Referenzformat ist **unser eigener
  Markdown-Export**, von Hand korrigiert: kein neues Format, das abdriften
  kann, und korrigieren statt abtippen. WER selbst implementiert (Levenshtein
  über Wortlisten, deutsche Normalisierung explizit, Zahlen bewusst **nicht**
  normalisiert). Keine DER — unsere Referenz hat keine Ende-Zeitstempel, eine
  geschätzte DER sähe präzise aus und wäre es nicht. Dazu `diarize=False` in
  der Pipeline (misst, was die Sprechertrennung kostet; nutzt denselben
  Fallback-Pfad wie ein pyannote-Fehler). 25 Unit-Tests; `--selftest` fährt
  über die Windows-Sprachausgabe einen bekannten Satz durch die volle Kette
  (WER 0,0 %, RTF 6,0). **Gefunden und behoben:** die erste Messung enthielt
  das Modell-Laden (420 s für 9 s Audio) — jetzt Warmlauf vor der Messung;
  und das umgebogene `APPDATA` duplizierte den Modell-Cache (2,9 GB), jetzt
  Verzeichnis-Junction auf den echten.
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
