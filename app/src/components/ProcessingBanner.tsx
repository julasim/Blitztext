// Top-of-view banner that shows live import progress for the active
// meeting. Driven by the `meeting.progress` sidecar events collected
// into useMeetingStore.progress.

import { Loader2 } from "lucide-react";
import { useMeetingStore, type ProgressInfo } from "../state/useMeetingStore";

const STAGE_LABEL: Record<ProgressInfo["stage"], string> = {
  decode: "Audio lesen",
  transcribe: "Transkribieren",
  diarize: "Sprecher erkennen",
  merge: "Zusammenführen",
  persist: "Speichern",
};

function fmtEta(sec?: number | null): string {
  if (sec == null || !isFinite(sec) || sec <= 0) return "";
  if (sec < 60) return `noch ~${Math.round(sec)}s`;
  return `noch ~${Math.round(sec / 60)} min`;
}

export function ProcessingBanner({ meetingId }: { meetingId: string }) {
  const p = useMeetingStore((s) => s.progress[meetingId]);
  const err = useMeetingStore((s) => s.importErrors[meetingId]);

  if (err) {
    return (
      <div
        style={{
          padding: "12px 20px",
          background: "var(--bt-red-bg)",
          color: "var(--bt-red-ink)",
          borderBottom: "1px solid var(--bt-red)",
          fontSize: "var(--fs-sm)",
          fontFamily: "var(--font-mono)",
        }}
      >
        Import fehlgeschlagen: {err}
      </div>
    );
  }

  if (!p) return null;

  const pct = Math.round((p.pct || 0) * 100);

  return (
    <div
      style={{
        padding: "10px 20px",
        borderBottom: "1px solid var(--bt-line)",
        background: "var(--bt-paper-2)",
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <Loader2 size={14} className="bt-spin" style={{ color: "var(--bt-ink)" }} />
      <span style={{ fontSize: "var(--fs-sm)", fontWeight: 500 }}>
        {STAGE_LABEL[p.stage]}
      </span>
      <div
        style={{
          flex: 1,
          height: 4,
          borderRadius: 2,
          background: "var(--bt-line)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: "var(--bt-ink)",
            transition: "width 200ms ease",
          }}
        />
      </div>
      <span
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "var(--fs-xs)",
          color: "var(--bt-subtle)",
          minWidth: 80,
          textAlign: "right",
        }}
      >
        {pct}% {fmtEta(p.eta_sec)}
      </span>
    </div>
  );
}
