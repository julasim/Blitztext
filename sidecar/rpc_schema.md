# Blitztext Sidecar — JSON-RPC Contract

**Source of truth** for the RPC methods and events exchanged between the Tauri shell and the Python sidecar. Implementation: `sidecar/methods.py` (+ `ping` in `sidecar/rpc.py`). TypeScript mirror: `app/src/lib/types.ts`.

Transport: line-delimited JSON-RPC 2.0 over stdin/stdout of the sidecar process.

> Stand 2026-07-27 — vollständig gegen `methods.py` abgeglichen. Wer eine
> Methode ergänzt, pflegt sie hier mit; das Dokument war schon einmal drei
> Namensräume hinterher.
>
> Die Namensräume `recording.*` (Mikrofon-Mitschnitt) und `dictate.*`
> (Hotkey-Diktat) sind am 2026-07-23 entfallen — die App transkribiert
> ausschließlich Dateien. Beide liegen in der Historie, letzter Stand vor
> Commit „Fokus: nur noch Datei-Transkription".

## Conventions

- Method names use dot notation: `namespace.action` (`meeting.import_file`, `speaker.rename`).
- All IDs are stringy (UUID4).
- Timestamps: `created_at` is ISO-8601 UTC; durations are milliseconds as integers.
- **Langlaufende Methoden antworten sofort** (meist nur mit der `meeting_id`) und
  arbeiten in einem Worker-Thread weiter. Der Fortschritt kommt ausschließlich
  über Notifications — wer auf das RPC-Ergebnis wartet, wartet vergebens.
- Errors follow JSON-RPC 2.0 (`code`, `message`, optional `data`). Application-specific codes:
  - `-32001` `APP_PIPELINE_FAILED` — transcription/diarization pipeline error.
  - `-32002` `APP_NOT_FOUND` — referenced meeting/speaker does not exist.
  - `-32003` `APP_DEPENDENCY_MISSING` — Ollama not reachable, HF token missing, etc.

## Method index (status legend: ✅ implemented · ⬜ planned)

### Meta

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `ping` | — | `{ok, version}` |
| ✅ | `config.get` | — | `{appdata, models_dir, meetings_dir, db_path, cuda_available, ollama_available, models[], audio_extensions[]}` — `models` ist `{id, label, hint}[]`; `id` geht als `whisper_model` durch die Queue |

### Meetings

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `meeting.import_file` | `{path, title?, language="de", whisper_model?, min_speakers?, max_speakers?}` | `{meeting_id, job_id}` — reiht in die Warteschlange ein und kehrt sofort zurück |
| ✅ | `meeting.list` | `{limit=100, offset=0}` | `MeetingListItem[]` |
| ✅ | `meeting.get` | `{id}` | `MeetingFull` |
| ✅ | `meeting.delete` | `{id}` | `{ok}` |
| ✅ | `meeting.set_title` | `{id, title}` | `{ok}` |

`whisper_model` default: `large-v3` mit CUDA, sonst `medium`
(`meeting_pipeline.pick_default_whisper_model`).

### Warteschlange

Importe laufen **seriell** durch einen einzigen Worker (`sidecar/jobs.py`).
Der Zustand liegt in der Tabelle `jobs` und überlebt einen Absturz.

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `queue.enqueue` | `{paths[], language="de", whisper_model?, min_speakers?, max_speakers?, vocabulary?}` | `{enqueued[], skipped[], count, vocabulary_dropped[]}` — nimmt Dateien **und Ordner** |
| ✅ | `queue.list` | `{limit=200}` | `Job[]` in Abarbeitungsreihenfolge |
| ✅ | `queue.state` | — | `{counts: {queued, running, done, failed, cancelled}, current_job_id, worker_alive}` |
| ✅ | `queue.cancel` | `{job_id}` | `{ok, state, pending}` — bei `pending: true` läuft der Job noch und bricht am nächsten Prüfpunkt ab |
| ✅ | `queue.clear_finished` | — | `{ok, removed}` — entfernt `done`/`failed`/`cancelled` |

```ts
type Job = {
  id: string
  meeting_id: string | null   // null nach Abbruch: die leere Hülle wird gelöscht,
                              // der Job-Eintrag bleibt als Historie
  source_path: string
  params: { language: string; whisper_model: string;
            min_speakers: number | null; max_speakers: number | null }
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  position: number            // FIFO-Schlüssel, monoton steigend
  attempts: number            // Wiederanläufe nach Absturz, max. 2
  error?: string
  created_at: string
  started_at?: string
  finished_at?: string
}
```

**Ordner:** `queue.enqueue` löst Verzeichnisse **rekursiv** auf und reiht
alphabetisch ein (`audio_io.expand_paths`). Das Frontend schaut bewusst nicht
selbst ins Dateisystem — es hat kein fs-Plugin mehr. Was nicht verarbeitet
werden kann, kommt als `skipped: [{path, reason}]` zurück statt still zu
verschwinden; die erlaubten Endungen liefert `config.get` → `audio_extensions`.

**Abbruch:** Ein wartender Job wird sofort verworfen. Ein laufender wird
vorgemerkt; die Pipeline prüft an den Stage-Grenzen und nach jedem
Whisper-Segment. Während der Diarization gibt es keinen Prüfpunkt — dort
greift der Abbruch erst danach.

**Wiederanlauf:** Steht beim Start ein Job auf `running`, war das ein
Absturz (nur ein Prozess besitzt die DB). Er geht zurück in die
Warteschlange, höchstens zweimal; danach `failed`.

### Speakers

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `speaker.rename` | `{meeting_id, speaker_id, name}` | `{ok}` |
| ✅ | `speaker.merge` | `{meeting_id, source_id, target_id}` | `{ok, merged_turns}` |
| ⬜ | `speaker.sample` | `{meeting_id, speaker_id, max_sec?}` | `{wav_path}` — 5-Sekunden-Hörprobe fürs Benennen; Rest aus Phase 1 |

### Cleanup & Export

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `cleanup.run` | `{meeting_id, model?, mode="faithful"}` | `{ok, started, total, mode}` — **async**; `mode ∈ {faithful, readable}`. Idempotent **je Stufe**: übersprungen wird nur, was schon in derselben Stufe bereinigt wurde (`turns.text_clean_mode`) |
| ✅ | `export.markdown` | `{meeting_id, path, use_cleanup=false}` | `{ok, bytes, path}` |

### Settings

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `settings.get` | — | `{hf_token_present, hf_token_hint}` |
| ✅ | `settings.get_vocabulary` | — | `{vocabulary}` — dauerhafte Firmen-Wortliste aus der `settings`-Tabelle |
| ✅ | `settings.set_vocabulary` | `{vocabulary}` | `{ok}` |
| ✅ | `settings.set_hf_token` | `{token}` | `{ok, stored}` — leerer String löscht die Credential |
| ✅ | `settings.test_hf_token` | — | `{ok, stage, user?, repos?, message}`, `stage ∈ {missing, deps, auth, gated, ready}`. `repos` = Zugriff je gated Diarization-Repo (3.1 **und** community-1); `ok` richtet sich nach dem Repo der installierten pyannote-Version |

Der HF-Token liegt im Windows-Anmeldeinformationsmanager (`keyring`, Dienst
`Blitztext`, Key `hf_token`) — nie in einer Datei, nie im Klartext an die UI.

## Server-initiated notifications (no `id`)

| Event | Payload |
|---|---|
| `meeting.progress` | `{meeting_id, stage, pct, eta_sec}` — `stage ∈ {decode, transcribe, diarize, merge, persist}`. **`pct` ist 0..1**, nicht 0..100, und bereits über alle fünf Stages gewichtet (5/55/30/5/5 %) |
| `meeting.done` | `{meeting_id}` |
| `meeting.error` | `{meeting_id, message}` |
| `meeting.warning` | `{meeting_id, stage, message, fallback}` — nicht-fatal. Kommt, wenn pyannote nicht lädt: der Import läuft mit einem Sprecher weiter (`fallback: "single_speaker"`) |
| `cleanup.progress` | `{meeting_id, processed, skipped, total, turn_id}` |
| `cleanup.done` | `{meeting_id, processed, skipped, total}` |
| `cleanup.error` | `{meeting_id, turn_id?, message}` — pro Turn, bricht den Lauf **nicht** ab |
| `queue.enqueued` | `{job_id, meeting_id, path}` |
| `queue.job_started` | `{job_id, meeting_id, path}` |
| `queue.job_done` | `{job_id, meeting_id}` |
| `queue.job_failed` | `{job_id, meeting_id, message}` — die Warteschlange läuft weiter |
| `queue.job_cancelled` | `{job_id, meeting_id}` |
| `queue.changed` | wie `queue.state` — nach jeder Änderung, für Zähler/Badges |
| `queue.recovered` | `{requeued: string[], failed: string[]}` — einmalig beim Start nach einem Absturz |

Auf der Rust-Seite werden alle Notifications als `window.emit("sidecar-event",
{event, params})` weitergereicht; das Frontend filtert mit `onEvent(name, …)`
aus `app/src/lib/rpc.ts`.

## Core types

```ts
type Turn = {
  id: string
  speaker_id: string
  idx: number
  start_ms: number
  end_ms: number
  text_raw: string
  text_clean?: string
  text_clean_mode?: 'faithful' | 'readable'   // welche Stufe geschrieben hat
  words: { t0: number; t1: number; w: string }[]
  overlap_flag: boolean
}

type Speaker = {
  id: string
  label: string          // e.g. "Speaker 1" — pyannote's output
  name?: string          // user-given display name
  color: string          // hex, from the 12-color palette
  word_count: number
  duration_ms: number
  share_pct: number      // 0..100
}

type MeetingListItem = {
  id: string
  title: string
  duration_ms: number
  created_at: string
  status: 'processing' | 'ready' | 'error'
}

type MeetingFull = MeetingListItem & {
  audio_path: string
  language: string
  whisper_model: string
  speakers: Speaker[]
  turns: Turn[]
}
```

## Example request/response

```jsonc
// → sent on stdin
{"jsonrpc":"2.0","id":1,"method":"ping"}

// ← written to stdout
{"jsonrpc":"2.0","id":1,"result":{"ok":true,"version":"0.1.0-alpha"}}
```

```jsonc
// Progress notification (no id, no response expected)
{"jsonrpc":"2.0","method":"meeting.progress",
 "params":{"meeting_id":"ab12","stage":"transcribe","pct":0.42,"eta_sec":73}}
```
