// Global state for the meeting library + currently-open meeting.
//
// The Python sidecar is the source of truth — every mutation goes through
// an RPC call and the local cache is refreshed from the response. We keep
// a simple flat state; meetings that aren't "active" hold only their list
// meta, the full record (with turns + speakers) is lazy-loaded.

import { create } from "zustand";
import { call, onEvent } from "../lib/rpc";
import type { Job, MeetingFull, MeetingListItem } from "../lib/types";

export type ProgressInfo = {
  stage: "decode" | "transcribe" | "diarize" | "merge" | "persist";
  pct: number; // 0..1
  eta_sec?: number | null;
};

/** Kopie ohne den Schlüssel `key` — für Fortschritts-Einträge, die nach
 *  meeting.done/error verschwinden sollen. */
function withoutKey<T>(map: Record<string, T>, key: string): Record<string, T> {
  if (!(key in map)) return map;
  const next = { ...map };
  delete next[key];
  return next;
}

type View =
  | { name: "library" }
  | { name: "import" }
  | { name: "review"; meetingId: string }
  | { name: "settings" };

export type ModelChoice = {
  id: string;
  label: string;
  hint: string;
};

type Config = {
  appdata: string;
  models_dir: string;
  meetings_dir: string;
  db_path: string;
  cuda_available: boolean;
  ollama_available: boolean;
  /** Wählbare ASR-Modelle — `id` geht als whisper_model durch die Queue. */
  models: ModelChoice[];
  whisper_models: string[];
  /** Vom Sidecar gepflegt — der Dateidialog führt keine eigene Liste. */
  audio_extensions: string[];
};

export type State = {
  // Routing
  view: View;
  goLibrary: () => void;
  goImport: () => void;
  goReview: (meetingId: string) => void;
  goSettings: () => void;

  // Config snapshot (loaded once on startup)
  config: Config | null;
  configError: string | null;
  loadConfig: () => Promise<void>;

  // Library
  meetings: MeetingListItem[];
  meetingsLoading: boolean;
  meetingsError: string | null;
  loadMeetings: () => Promise<void>;
  deleteMeeting: (id: string) => Promise<void>;

  // Active meeting
  active: MeetingFull | null;
  activeLoading: boolean;
  activeError: string | null;
  loadMeeting: (id: string) => Promise<void>;
  renameSpeaker: (speakerId: string, name: string) => Promise<void>;
  mergeSpeakers: (sourceId: string, targetId: string) => Promise<void>;
  setTitle: (title: string) => Promise<void>;

  // Cleanup
  cleanupRunning: boolean;
  cleanupError: string | null;
  runCleanup: () => Promise<void>;

  // Derived helpers
  useCleanup: boolean;
  setUseCleanup: (v: boolean) => void;

  // Import-Warteschlange. Die DB im Sidecar ist die Wahrheit; wir laden
  // die Liste neu, sobald ein queue.*-Event kommt, statt lokal mitzuzählen.
  jobs: Job[];
  loadJobs: () => Promise<void>;
  enqueue: (
    paths: string[],
    options?: { whisper_model?: string; language?: string },
  ) => Promise<{ count: number; skipped: SkippedPath[] }>;
  cancelJob: (jobId: string) => Promise<void>;
  clearFinishedJobs: () => Promise<void>;

  // Per-meeting pipeline progress (keyed by meeting_id). Populated by
  // sidecar-event subscriptions — see wireSidecarEvents().
  progress: Record<string, ProgressInfo>;
  importErrors: Record<string, string>;
  wireSidecarEvents: () => Promise<() => void>;
};

export type SkippedPath = { path: string; reason: string };

export const useMeetingStore = create<State>((set, get) => ({
  view: { name: "library" },
  goLibrary: () => set({ view: { name: "library" } }),
  goImport: () => set({ view: { name: "import" } }),
  goReview: (meetingId) => {
    set({ view: { name: "review", meetingId } });
    void get().loadMeeting(meetingId);
  },
  goSettings: () => set({ view: { name: "settings" } }),

  config: null,
  configError: null,
  async loadConfig() {
    try {
      const cfg = await call<Config>("config.get");
      set({ config: cfg, configError: null });
    } catch (e) {
      set({ configError: e instanceof Error ? e.message : String(e) });
    }
  },

  meetings: [],
  meetingsLoading: false,
  meetingsError: null,
  async loadMeetings() {
    set({ meetingsLoading: true, meetingsError: null });
    try {
      const list = await call<MeetingListItem[]>("meeting.list", { limit: 200 });
      set({ meetings: list, meetingsLoading: false });
    } catch (e) {
      set({
        meetingsLoading: false,
        meetingsError: e instanceof Error ? e.message : String(e),
      });
    }
  },
  async deleteMeeting(id) {
    await call("meeting.delete", { id });
    // Optimistic local update, then reload.
    set((s) => ({
      meetings: s.meetings.filter((m) => m.id !== id),
      active: s.active?.id === id ? null : s.active,
    }));
  },

  active: null,
  activeLoading: false,
  activeError: null,
  async loadMeeting(id) {
    set({ activeLoading: true, activeError: null });
    try {
      const m = await call<MeetingFull>("meeting.get", { id });
      set({ active: m, activeLoading: false });
    } catch (e) {
      set({
        activeLoading: false,
        activeError: e instanceof Error ? e.message : String(e),
      });
    }
  },
  async renameSpeaker(speakerId, name) {
    const active = get().active;
    if (!active) return;
    // Optimistic
    set({
      active: {
        ...active,
        speakers: active.speakers.map((s) =>
          s.id === speakerId ? { ...s, name } : s,
        ),
      },
    });
    try {
      await call("speaker.rename", {
        meeting_id: active.id,
        speaker_id: speakerId,
        name,
      });
    } catch (e) {
      // Revert + surface
      set({ activeError: e instanceof Error ? e.message : String(e) });
      void get().loadMeeting(active.id);
    }
  },
  async mergeSpeakers(sourceId, targetId) {
    const active = get().active;
    if (!active) return;
    await call("speaker.merge", {
      meeting_id: active.id,
      source_id: sourceId,
      target_id: targetId,
    });
    void get().loadMeeting(active.id);
  },
  async setTitle(title) {
    const active = get().active;
    if (!active) return;
    set({ active: { ...active, title } });
    await call("meeting.set_title", { id: active.id, title });
    void get().loadMeetings();
  },

  cleanupRunning: false,
  cleanupError: null,
  async runCleanup() {
    // Async pattern: kick the sidecar off, the cleanup.* events take over
    // from there. cleanupRunning stays true until the .done event fires.
    const active = get().active;
    if (!active) return;
    set({ cleanupRunning: true, cleanupError: null });
    try {
      await call("cleanup.run", { meeting_id: active.id });
      // Don't refresh here — wait for cleanup.done.
    } catch (e) {
      set({
        cleanupRunning: false,
        cleanupError: e instanceof Error ? e.message : String(e),
      });
    }
  },

  useCleanup: false,
  setUseCleanup: (v) => set({ useCleanup: v }),

  jobs: [],
  async loadJobs() {
    try {
      const list = await call<Job[]>("queue.list", { limit: 200 });
      set({ jobs: list });
    } catch (e) {
      console.warn("[queue.list] failed:", e);
    }
  },
  async enqueue(paths, options) {
    const res = await call<{ count: number; skipped: SkippedPath[] }>(
      "queue.enqueue",
      { paths, ...options },
    );
    await Promise.all([get().loadJobs(), get().loadMeetings()]);
    return res;
  },
  async cancelJob(jobId) {
    await call("queue.cancel", { job_id: jobId });
    await Promise.all([get().loadJobs(), get().loadMeetings()]);
  },
  async clearFinishedJobs() {
    await call("queue.clear_finished");
    await get().loadJobs();
  },

  progress: {},
  importErrors: {},
  async wireSidecarEvents() {
    const offProgress = await onEvent<{
      meeting_id: string;
      stage: ProgressInfo["stage"];
      pct: number;
      eta_sec?: number;
    }>("meeting.progress", (p) => {
      set((s) => ({
        progress: {
          ...s.progress,
          [p.meeting_id]: { stage: p.stage, pct: p.pct, eta_sec: p.eta_sec },
        },
      }));
    });
    const offDone = await onEvent<{ meeting_id: string }>(
      "meeting.done",
      (p) => {
        // Drop the progress entry + refresh the meeting + the library list.
        set((s) => ({ progress: withoutKey(s.progress, p.meeting_id) }));
        void get().loadMeetings();
        const active = get().active;
        if (active?.id === p.meeting_id) void get().loadMeeting(p.meeting_id);
        // Windows toast — best-effort, ask permission lazily.
        void notifyMeetingDone(p.meeting_id);
      },
    );
    const offError = await onEvent<{ meeting_id: string; message: string }>(
      "meeting.error",
      (p) => {
        set((s) => ({
          importErrors: { ...s.importErrors, [p.meeting_id]: p.message },
          progress: withoutKey(s.progress, p.meeting_id),
        }));
        void get().loadMeetings();
      },
    );
    const offCleanupDone = await onEvent<{
      meeting_id: string;
      processed: number;
      skipped: number;
      total: number;
    }>("cleanup.done", (p) => {
      set({ cleanupRunning: false, useCleanup: true });
      const active = get().active;
      if (active?.id === p.meeting_id) void get().loadMeeting(p.meeting_id);
    });
    const offCleanupError = await onEvent<{
      meeting_id: string;
      message: string;
    }>("cleanup.error", (p) => {
      set({
        cleanupRunning: false,
        cleanupError: p.message,
      });
    });
    // Warteschlange: jede Änderung im Sidecar → Liste neu holen. Das ist
    // ein RPC pro Zustandswechsel und damit billig; lokales Mitzählen
    // würde bei Abbruch und Wiederanlauf zwangsläufig auseinanderlaufen.
    const offQueueChanged = await onEvent("queue.changed", () => {
      void get().loadJobs();
    });
    const offQueueFinished = await Promise.all(
      ["queue.job_done", "queue.job_failed", "queue.job_cancelled"].map((name) =>
        onEvent(name, () => {
          void get().loadJobs();
          void get().loadMeetings();
        }),
      ),
    );

    return () => {
      offProgress();
      offDone();
      offError();
      offCleanupDone();
      offCleanupError();
      offQueueChanged();
      for (const off of offQueueFinished) off();
    };
  },
}));

// --- Helpers --------------------------------------------------------------

async function notifyMeetingDone(meetingId: string): Promise<void> {
  try {
    const meta = await call<{ title: string; duration_ms: number }>(
      "meeting.get",
      { id: meetingId },
    );
    const mins = Math.round((meta.duration_ms || 0) / 60000);
    const {
      isPermissionGranted,
      requestPermission,
      sendNotification,
    } = await import("@tauri-apps/plugin-notification");

    let granted = await isPermissionGranted();
    if (!granted) {
      const r = await requestPermission();
      granted = r === "granted";
    }
    if (!granted) return;
    sendNotification({
      title: "Transkript fertig",
      body: `${meta.title} · ${mins ? mins + " min" : "kurz"}`,
    });
  } catch (e) {
    console.warn("[notify] meeting.done toast failed:", e);
  }
}
