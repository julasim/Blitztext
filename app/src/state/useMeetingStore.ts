// Global state for the meeting library + currently-open meeting.
//
// The Python sidecar is the source of truth — every mutation goes through
// an RPC call and the local cache is refreshed from the response. We keep
// a simple flat state; meetings that aren't "active" hold only their list
// meta, the full record (with turns + speakers) is lazy-loaded.

import { create } from "zustand";
import { call, onEvent } from "../lib/rpc";
import type { MeetingFull, MeetingListItem } from "../lib/types";

export type ProgressInfo = {
  stage: "decode" | "transcribe" | "diarize" | "merge" | "persist";
  pct: number; // 0..1
  eta_sec?: number | null;
};

type View =
  | { name: "library" }
  | { name: "import" }
  | { name: "review"; meetingId: string }
  | { name: "settings" };

type Config = {
  appdata: string;
  models_dir: string;
  meetings_dir: string;
  db_path: string;
  cuda_available: boolean;
  ollama_available: boolean;
  whisper_models: string[];
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

  // Per-meeting pipeline progress (keyed by meeting_id). Populated by
  // sidecar-event subscriptions — see wireSidecarEvents().
  progress: Record<string, ProgressInfo>;
  importErrors: Record<string, string>;
  wireSidecarEvents: () => Promise<() => void>;
};

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
    const active = get().active;
    if (!active) return;
    set({ cleanupRunning: true, cleanupError: null });
    try {
      await call("cleanup.run", { meeting_id: active.id });
      await get().loadMeeting(active.id);
      set({ useCleanup: true });
    } catch (e) {
      set({
        cleanupError: e instanceof Error ? e.message : String(e),
      });
    } finally {
      set({ cleanupRunning: false });
    }
  },

  useCleanup: false,
  setUseCleanup: (v) => set({ useCleanup: v }),

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
        set((s) => {
          const { [p.meeting_id]: _drop, ...rest } = s.progress;
          return { progress: rest };
        });
        void get().loadMeetings();
        const active = get().active;
        if (active?.id === p.meeting_id) void get().loadMeeting(p.meeting_id);
      },
    );
    const offError = await onEvent<{ meeting_id: string; message: string }>(
      "meeting.error",
      (p) => {
        set((s) => ({
          importErrors: { ...s.importErrors, [p.meeting_id]: p.message },
          progress: (() => {
            const { [p.meeting_id]: _drop, ...rest } = s.progress;
            return rest;
          })(),
        }));
        void get().loadMeetings();
      },
    );
    return () => {
      offProgress();
      offDone();
      offError();
    };
  },
}));
