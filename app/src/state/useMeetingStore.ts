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
  /** Zeitstempel des ersten Fortschritts-Events dieses Imports (ms).
   *  Grundlage der Restzeit-Schätzung — das Backend liefert keine. */
  startedAt: number;
  /** Laufzeit der zuletzt **abgeschlossenen** Stufe. Ausdrücklich keine
   *  Restzeit; genau diese Verwechslung stand vorher in der Oberfläche. */
  stageElapsedSec?: number | null;
};

/** Kopie ohne den Schlüssel `key` — für Fortschritts-Einträge, die nach
 *  meeting.done/error verschwinden sollen. */
function withoutKey<T>(map: Record<string, T>, key: string): Record<string, T> {
  if (!(key in map)) return map;
  const next = { ...map };
  delete next[key];
  return next;
}

/** Fehlertext aus allem, was ein `catch` liefern kann. */
function fehlertext(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
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
  /** Was der Sidecar ohne ausdrückliche Wahl nimmt (ohne GPU: `medium`). */
  whisper_default: string;
  /** Ollama-Modell des LLM-Cleanups. */
  cleanup_model: string;
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
  /** `false`, wenn das Löschen fehlschlug — der Aufrufer darf dann nicht
   *  zur Bibliothek wechseln, als wäre alles gut gegangen. */
  deleteMeeting: (id: string) => Promise<boolean>;

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
  /** `faithful` entfernt nur Füllwörter, `readable` darf zusätzlich
   *  Satzzeichen setzen und angefangene Sätze zu Ende führen. Der Rohtext
   *  bleibt in beiden Fällen erhalten. */
  cleanupMode: CleanupMode;
  setCleanupMode: (mode: CleanupMode) => void;
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
    options?: {
      whisper_model?: string;
      language?: string;
      vocabulary?: string;
      /** Bekannte Teilnehmerzahl — ohne Vorgabe schätzt pyannote selbst. */
      min_speakers?: number;
      max_speakers?: number;
    },
  ) => Promise<{
    count: number;
    skipped: SkippedPath[];
    vocabulary_dropped: string[];
  }>;
  cancelJob: (jobId: string) => Promise<void>;
  clearFinishedJobs: () => Promise<void>;

  // Per-meeting pipeline progress (keyed by meeting_id). Populated by
  // sidecar-event subscriptions — see wireSidecarEvents().
  progress: Record<string, ProgressInfo>;
  importErrors: Record<string, string>;
  wireSidecarEvents: () => Promise<() => void>;

  /** Fehler einer schreibenden Aktion (Löschen, Umbenennen, Zusammenführen,
   *  Abbrechen). Vorher scheiterten diese Pfade **stumm** — der Nutzer
   *  klickte, nichts geschah, und keine Meldung erklärte warum. */
  actionError: string | null;
  clearActionError: () => void;

  /** Nicht-fatale Warnungen je Meeting, allen voran der Ausfall der
   *  Sprechertrennung. Das Backend sendet dafür `meeting.warning`; ohne
   *  Abnehmer lieferte der Import ein Transkript mit genau einem Sprecher
   *  aus, ohne dass irgendwo stand warum. */
  warnings: Record<string, string>;
  dismissWarning: (meetingId: string) => void;

  /** Fortschritt des LLM-Cleanups (Absätze). Ein Lauf über 80 Absätze
   *  dauert Minuten — ohne Zahl steht die UI scheinbar still. */
  cleanupProgress: { processed: number; skipped: number; total: number } | null;

  // --- Sachprotokoll ---
  //
  // Verdichtet das Transkript zu dem, was in eine Projektakte gehört:
  // besprochene Sachverhalte, Hinweise, Entscheidungen, offene Punkte.
  // Etwas anderes als der Cleanup, der nur Füllwörter entfernt.
  /** Das erzeugte Protokoll des offenen Meetings, falls vorhanden. */
  protocol: string | null;
  protocolRunning: boolean;
  protocolError: string | null;
  protocolProgress: { done: number; total: number } | null;
  loadProtocol: (meetingId: string) => Promise<void>;
  runProtocol: () => Promise<void>;
};

export type SkippedPath = { path: string; reason: string };

/** Stufen des LLM-Cleanups, siehe `core/llm.py`. */
export type CleanupMode = "faithful" | "readable";

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
    try {
      await call("meeting.delete", { id });
    } catch (e) {
      set({ actionError: `Löschen fehlgeschlagen: ${fehlertext(e)}` });
      return false;
    }
    set((s) => ({
      meetings: s.meetings.filter((m) => m.id !== id),
      active: s.active?.id === id ? null : s.active,
      actionError: null,
    }));
    return true;
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
      // Zurücksetzen und melden. Die Meldung geht bewusst nach `actionError`
      // und nicht nach `activeError`: das folgende loadMeeting() setzt
      // `activeError` auf null und hätte sie sofort wieder gelöscht, bevor
      // sie jemand lesen kann.
      set({ actionError: `Umbenennen fehlgeschlagen: ${fehlertext(e)}` });
      await get().loadMeeting(active.id);
    }
  },
  async mergeSpeakers(sourceId, targetId) {
    const active = get().active;
    if (!active) return;
    try {
      await call("speaker.merge", {
        meeting_id: active.id,
        source_id: sourceId,
        target_id: targetId,
      });
      set({ actionError: null });
    } catch (e) {
      set({ actionError: `Zusammenführen fehlgeschlagen: ${fehlertext(e)}` });
    }
    await get().loadMeeting(active.id);
  },
  async setTitle(title) {
    const active = get().active;
    if (!active) return;
    const vorher = active.title;
    set({ active: { ...active, title } });
    try {
      await call("meeting.set_title", { id: active.id, title });
    } catch (e) {
      // Ohne Rücknahme stünden hier drei verschiedene Titel: der neue in der
      // Überschrift, der alte in der Seitenleiste, der alte in der DB.
      set((s) => ({
        active: s.active ? { ...s.active, title: vorher } : s.active,
        actionError: `Titel konnte nicht gespeichert werden: ${fehlertext(e)}`,
      }));
      return;
    }
    set({ actionError: null });
    await get().loadMeetings();
  },

  cleanupRunning: false,
  cleanupError: null,
  cleanupMode: "faithful",
  setCleanupMode: (mode) => set({ cleanupMode: mode }),
  async runCleanup() {
    // Async pattern: kick the sidecar off, the cleanup.* events take over
    // from there. cleanupRunning stays true until the .done event fires.
    const active = get().active;
    if (!active) return;
    if (get().cleanupRunning) return; // kein zweiter Lauf auf denselben Daten
    set({ cleanupRunning: true, cleanupError: null, cleanupProgress: null });
    try {
      await call("cleanup.run", {
        meeting_id: active.id,
        mode: get().cleanupMode,
      });
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
    const res = await call<{
      count: number;
      skipped: SkippedPath[];
      vocabulary_dropped: string[];
    }>("queue.enqueue", { paths, ...options });
    await Promise.all([get().loadJobs(), get().loadMeetings()]);
    return res;
  },
  async cancelJob(jobId) {
    try {
      await call("queue.cancel", { job_id: jobId });
      set({ actionError: null });
    } catch (e) {
      set({ actionError: `Abbrechen fehlgeschlagen: ${fehlertext(e)}` });
    }
    await Promise.all([get().loadJobs(), get().loadMeetings()]);
  },
  async clearFinishedJobs() {
    try {
      await call("queue.clear_finished");
      set({ actionError: null });
    } catch (e) {
      set({ actionError: `Aufräumen fehlgeschlagen: ${fehlertext(e)}` });
    }
    await get().loadJobs();
  },

  progress: {},
  importErrors: {},
  async wireSidecarEvents() {
    const offProgress = await onEvent<{
      meeting_id: string;
      stage: ProgressInfo["stage"];
      pct: number;
      stage_elapsed_sec?: number;
    }>("meeting.progress", (p) => {
      set((s) => {
        const bisher = s.progress[p.meeting_id];
        return {
          progress: {
            ...s.progress,
            [p.meeting_id]: {
              stage: p.stage,
              pct: p.pct,
              // Startzeit über die Events hinweg festhalten — sie ist der
              // Bezugspunkt für die Restzeit-Schätzung.
              startedAt: bisher?.startedAt ?? Date.now(),
              stageElapsedSec: p.stage_elapsed_sec,
            },
          },
          // Läuft wieder etwas, ist der Fehler des Vorlaufs erledigt. Ohne
          // das verdeckte er dauerhaft den Fortschrittsbalken — die Anzeige
          // prüft den Fehler zuerst.
          importErrors: withoutKey(s.importErrors, p.meeting_id),
        };
      });
    });
    const offDone = await onEvent<{ meeting_id: string }>(
      "meeting.done",
      (p) => {
        // Drop the progress entry + refresh the meeting + the library list.
        set((s) => ({ progress: withoutKey(s.progress, p.meeting_id) }));
        void (async () => {
          await get().loadMeetings();
          const meta = get().meetings.find((m) => m.id === p.meeting_id);
          // Windows toast — best-effort, ask permission lazily.
          if (meta) void notifyMeetingDone(meta);
        })();
        const active = get().active;
        if (active?.id === p.meeting_id) void get().loadMeeting(p.meeting_id);
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
    // Sprechertrennung ausgefallen (Token, Lizenz, CUDA): der Import läuft
    // mit EINEM Sprecher weiter. Ohne diesen Abnehmer sah das Ergebnis aus
    // wie ein normales Transkript, und niemand erfuhr den Grund.
    const offWarning = await onEvent<{
      meeting_id: string;
      stage: string;
      message: string;
    }>("meeting.warning", (p) => {
      set((s) => ({
        warnings: { ...s.warnings, [p.meeting_id]: p.message },
      }));
    });
    const offCleanupProgress = await onEvent<{
      meeting_id: string;
      processed: number;
      skipped: number;
      total: number;
    }>("cleanup.progress", (p) => {
      set({
        cleanupProgress: {
          processed: p.processed,
          skipped: p.skipped,
          total: p.total,
        },
      });
    });
    const offCleanupDone = await onEvent<{
      meeting_id: string;
      processed: number;
      skipped: number;
      total: number;
    }>("cleanup.done", (p) => {
      // cleanupError mit zurücksetzen: sonst bleibt die Meldung eines
      // einzelnen misslungenen Absatzes für immer stehen — auch über
      // spätere, fehlerfreie Läufe und andere Meetings hinweg.
      set({
        cleanupRunning: false,
        cleanupError: null,
        cleanupProgress: null,
        useCleanup: true,
      });
      const active = get().active;
      if (active?.id === p.meeting_id) void get().loadMeeting(p.meeting_id);
    });
    const offCleanupError = await onEvent<{
      meeting_id: string;
      message: string;
      fatal?: boolean;
    }>("cleanup.error", (p) => {
      // Das Backend meldet diesen Fehler AUCH je misslungenem Absatz und
      // arbeitet danach weiter. Nur beim fatalen Fall darf die Anzeige
      // enden — sonst wird der Knopf wieder aktiv, während der Worker noch
      // läuft, und ein zweiter Klick startet einen Parallellauf.
      set({
        cleanupError: p.message,
        ...(p.fatal ? { cleanupRunning: false, cleanupProgress: null } : {}),
      });
    });
    // Nach einem Absturz wieder eingereihte oder endgültig aufgegebene Jobs.
    const offRecovered = await onEvent("queue.recovered", () => {
      void get().loadJobs();
      void get().loadMeetings();
    });
    const offProtocolProgress = await onEvent<{
      meeting_id: string;
      done: number;
      total: number;
    }>("protocol.progress", (p) => {
      set({ protocolProgress: { done: p.done, total: p.total } });
    });
    const offProtocolDone = await onEvent<{ meeting_id: string }>(
      "protocol.done",
      (p) => {
        set({ protocolRunning: false, protocolProgress: null, protocolError: null });
        void get().loadProtocol(p.meeting_id);
      },
    );
    const offProtocolError = await onEvent<{
      meeting_id: string;
      message: string;
    }>("protocol.error", (p) => {
      set({
        protocolRunning: false,
        protocolProgress: null,
        protocolError: p.message,
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
      offWarning();
      offCleanupProgress();
      offCleanupDone();
      offCleanupError();
      offQueueChanged();
      offRecovered();
      offProtocolProgress();
      offProtocolDone();
      offProtocolError();
      for (const off of offQueueFinished) off();
    };
  },

  protocol: null,
  protocolRunning: false,
  protocolError: null,
  protocolProgress: null,
  async loadProtocol(meetingId) {
    try {
      const res = await call<{ exists: boolean; markdown: string }>(
        "protocol.get",
        { meeting_id: meetingId },
      );
      set({ protocol: res.exists ? res.markdown : null });
    } catch (e) {
      // Kein actionError: das Fehlen eines Protokolls ist der Normalfall,
      // und der Nutzer hat hier nichts angestoßen.
      console.warn("[protocol.get] failed:", e);
      set({ protocol: null });
    }
  },
  async runProtocol() {
    const active = get().active;
    if (!active || get().protocolRunning) return;
    set({ protocolRunning: true, protocolError: null, protocolProgress: null });
    try {
      await call("protocol.generate", { meeting_id: active.id });
      // Fertig meldet das protocol.done-Ereignis.
    } catch (e) {
      set({ protocolRunning: false, protocolError: fehlertext(e) });
    }
  },

  actionError: null,
  clearActionError: () => set({ actionError: null }),

  warnings: {},
  dismissWarning: (meetingId) =>
    set((s) => ({ warnings: withoutKey(s.warnings, meetingId) })),

  cleanupProgress: null,
}));

// --- Helpers --------------------------------------------------------------

/** Windows-Toast nach einem fertigen Import.
 *
 * Nimmt die Metadaten aus der bereits geladenen Liste. Vorher holte diese
 * Funktion das **vollständige** Meeting über `meeting.get` — mit allen Turns
 * und sämtlichen Wort-Zeitstempeln, also mehrere MB in einer einzigen Zeile
 * über die stdio-Pipe, nur um Titel und Dauer zu lesen. */
async function notifyMeetingDone(meta: {
  title: string;
  duration_ms: number;
}): Promise<void> {
  try {
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
