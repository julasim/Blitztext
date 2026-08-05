// TypeScript mirror of sidecar RPC schemas.
// Source of truth: sidecar/rpc_schema.md — keep these in sync.

export type Word = { t0: number; t1: number; w: string };

export type Turn = {
  id: string;
  speaker_id: string;
  idx: number;
  start_ms: number;
  end_ms: number;
  text_raw: string;
  text_clean?: string;
  /** Welche Cleanup-Stufe `text_clean` geschrieben hat. */
  text_clean_mode?: "faithful" | "readable";
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

export type JobState =
  | "queued"
  | "running"
  | "done"
  | "failed"
  | "cancelled";

export type Job = {
  id: string;
  // null nach einem Abbruch: die leere Meeting-Hülle wird gelöscht, der
  // Job-Eintrag bleibt als Historie stehen.
  meeting_id: string | null;
  source_path: string;
  params: {
    language: string;
    whisper_model: string;
    min_speakers: number | null;
    max_speakers: number | null;
  };
  state: JobState;
  position: number;
  attempts: number;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type MeetingFull = MeetingListItem & {
  audio_path: string;
  language: string;
  whisper_model: string;
  speakers: Speaker[];
  turns: Turn[];
};
