// TypeScript mirror of sidecar RPC schemas.
// Source of truth: sidecar/rpc_schema.md — keep these in sync.

export type PingResult = {
  ok: boolean;
  version: string;
};

// --- Planned (Phase 1) — stubs so the rest of the app can import them early ---

export type Word = { t0: number; t1: number; w: string };

export type Turn = {
  id: string;
  speaker_id: string;
  idx: number;
  start_ms: number;
  end_ms: number;
  text_raw: string;
  text_clean?: string;
  words: Word[];
  overlap_flag: boolean;
};

export type Speaker = {
  id: string;
  label: string;
  name?: string;
  color: string;
  word_count: number;
  duration_ms: number;
  share_pct: number;
};

export type MeetingListItem = {
  id: string;
  title: string;
  duration_ms: number;
  created_at: string;
  status: "processing" | "ready" | "error";
};

export type MeetingFull = MeetingListItem & {
  audio_path: string;
  language: string;
  whisper_model: string;
  speakers: Speaker[];
  turns: Turn[];
};
