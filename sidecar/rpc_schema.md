# Blitztext Sidecar — JSON-RPC Contract

**Source of truth** for the RPC methods and events exchanged between the Tauri shell and the Python sidecar. Implementation: `sidecar/methods.py` (+ `ping` in `sidecar/rpc.py`). TypeScript mirror: `app/src/lib/types.ts`.

Transport: line-delimited JSON-RPC 2.0 over stdin/stdout of the sidecar process.

> Stand 2026-07-23 — vollständig gegen `methods.py` abgeglichen. Wer eine
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
| ✅ | `config.get` | — | `{appdata, models_dir, meetings_dir, db_path, cuda_available, ollama_available, whisper_models[], python_executable}` |

### Meetings

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `meeting.import_file` | `{path, title?, language="de", whisper_model?, min_speakers?, max_speakers?}` | `{meeting_id}` — **async**, treibt `meeting.progress`/`done`/`error` |
| ✅ | `meeting.list` | `{limit=100, offset=0}` | `MeetingListItem[]` |
| ✅ | `meeting.get` | `{id}` | `MeetingFull` |
| ✅ | `meeting.delete` | `{id}` | `{ok}` |
| ✅ | `meeting.set_title` | `{id, title}` | `{ok}` |

`whisper_model` default: `large-v3` mit CUDA, sonst `medium`
(`meeting_pipeline.pick_default_whisper_model`).

### Speakers

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `speaker.rename` | `{meeting_id, speaker_id, name}` | `{ok}` |
| ✅ | `speaker.merge` | `{meeting_id, source_id, target_id}` | `{ok, merged_turns}` |
| ⬜ | `speaker.sample` | `{meeting_id, speaker_id, max_sec?}` | `{wav_path}` — 5-Sekunden-Hörprobe fürs Benennen; Rest aus Phase 1 |

### Cleanup & Export

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `cleanup.run` | `{meeting_id, model?}` | `{ok, started, total}` — **async**; idempotent, bereits bereinigte Turns werden übersprungen |
| ✅ | `export.markdown` | `{meeting_id, path, use_cleanup=false}` | `{ok, bytes, path}` |

### Settings

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `settings.get` | — | `{hf_token_present, hf_token_hint, whisper_default, ollama_default}` |
| ✅ | `settings.set_hf_token` | `{token}` | `{ok, stored}` — leerer String löscht die Credential |
| ✅ | `settings.test_hf_token` | — | `{ok, stage, user?, message}`, `stage ∈ {missing, deps, auth, gated, ready}` |

Der HF-Token liegt im Windows-Anmeldeinformationsmanager (`keyring`, Dienst
`Blitztext`, Key `hf_token`) — nie in einer Datei, nie im Klartext an die UI.

## Server-initiated notifications (no `id`)

| Event | Payload |
|---|---|
| `meeting.progress` | `{meeting_id, stage, pct, eta_sec}` — `stage ∈ {decode, transcribe, diarize, merge, persist}`. **`pct` ist 0..1**, nicht 0..100, und bereits über alle fünf Stages gewichtet (5/55/30/5/5 %) |
| `meeting.done` | `{meeting_id}` |
| `meeting.error` | `{meeting_id, message}` (bei WAV-Export zusätzlich `stage`) |
| `meeting.warning` | `{meeting_id, stage, message, fallback}` — nicht-fatal. Kommt, wenn pyannote nicht lädt: der Import läuft mit einem Sprecher weiter (`fallback: "single_speaker"`) |
| `cleanup.progress` | `{meeting_id, processed, skipped, total, turn_id}` |
| `cleanup.done` | `{meeting_id, processed, skipped, total}` |
| `cleanup.error` | `{meeting_id, turn_id?, message}` — pro Turn, bricht den Lauf **nicht** ab |

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
