# Blitztext Sidecar — JSON-RPC Contract

**Source of truth** for the RPC methods and events exchanged between the Tauri shell and the Python sidecar. TypeScript mirror: `app/src/lib/types.ts`.

Transport: line-delimited JSON-RPC 2.0 over stdin/stdout of the sidecar process.

## Conventions

- Method names use dot notation: `namespace.action` (`meeting.import_file`, `speaker.rename`).
- All IDs are stringy (UUID4).
- Timestamps: `created_at` is ISO-8601 UTC; durations are milliseconds as integers.
- Errors follow JSON-RPC 2.0 (`code`, `message`, optional `data`). Application-specific codes:
  - `-32001` `APP_PIPELINE_FAILED` — transcription/diarization pipeline error.
  - `-32002` `APP_NOT_FOUND` — referenced meeting/speaker does not exist.
  - `-32003` `APP_DEPENDENCY_MISSING` — Ollama not reachable, HF token missing, etc.

## Method index (status legend: ✅ implemented · 🚧 stub · ⬜ planned)

| Status | Method | Request | Response |
|---|---|---|---|
| ✅ | `ping` | — | `{ok, version}` |
| ✅ | `config.get` | — | `{appdata, models_dir, meetings_dir, db_path, cuda_available, ollama_available, whisper_models[], python_executable}` |
| 🚧 | `meeting.import_file` | `{path, title?}` | `{meeting_id}` — stub, needs torch+pyannote |
| ✅ | `meeting.list` | `{limit?, offset?}` | `MeetingListItem[]` |
| ✅ | `meeting.get` | `{id}` | `MeetingFull` |
| ✅ | `meeting.delete` | `{id}` | `{ok}` |
| ✅ | `meeting.set_title` | `{id, title}` | `{ok}` |
| ✅ | `speaker.rename` | `{meeting_id, speaker_id, name}` | `{ok}` |
| ✅ | `speaker.merge` | `{meeting_id, source_id, target_id}` | `{ok, merged_turns}` |
| ⬜ | `speaker.sample` | `{meeting_id, speaker_id, max_sec?}` | `{wav_path}` |
| 🚧 | `cleanup.run` | `{meeting_id, model?}` | `{ok}` — stub, needs Ollama wiring |
| ⬜ | `cleanup.status` | `{meeting_id}` | `{state, progress}` |
| ⬜ | `export.markdown` | `{meeting_id, use_cleanup, path}` | `{ok, bytes}` |
| ⬜ | `settings.update` | `{...}` | `{ok}` |

## Server-initiated notifications (no `id`)

| Event | Payload |
|---|---|
| `meeting.progress` | `{meeting_id, stage, pct, eta_sec}` — `stage ∈ {decode, transcribe, diarize, merge, persist}` |
| `meeting.done` | `{meeting_id}` |
| `meeting.error` | `{meeting_id, stage, message}` |
| `cleanup.turn_done` | `{meeting_id, turn_id}` |

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
 "params":{"meeting_id":"ab12","stage":"transcribe","pct":42,"eta_sec":73}}
```
