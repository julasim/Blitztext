// Top-of-view banner that shows live import progress for the active
// meeting. Driven by the `meeting.progress` sidecar events collected
// into useMeetingStore.progress.

import { Loader2 } from "lucide-react";
import { STAGE_LABEL } from "../lib/format";
import { useMeetingStore, type ProgressInfo } from "../state/useMeetingStore";

/** Restzeit aus dem bisherigen Tempo schätzen.
 *
 * Das Backend liefert keine Restzeit. Bis 2026-08-05 zeigte diese Stelle
 * `eta_sec` an — das war die **verstrichene** Laufzeit der gerade beendeten
 * Stufe, also nachweislich das Gegenteil dessen, was „noch ~X s" verspricht.
 * Jetzt: verstrichene Zeit / erreichter Anteil ⇒ Gesamtdauer ⇒ Rest.
 */
function fmtRestzeit(p: ProgressInfo): string {
  // Unter 2 % ist die Hochrechnung wertlos (und zeigt Fantasiezahlen).
  if (!p.pct || p.pct < 0.02 || p.pct >= 1) return "";
  const verstrichen = (Date.now() - p.startedAt) / 1000;
  if (verstrichen < 3) return "";
  const rest = (verstrichen * (1 - p.pct)) / p.pct;
  if (!isFinite(rest) || rest <= 0) return "";
  // Auf 5 s bzw. volle Minuten runden — Sekundengenauigkeit täuscht eine
  // Präzision vor, die eine Hochrechnung nicht hat.
  if (rest < 60) return `noch ~${Math.max(5, Math.round(rest / 5) * 5)}s`;
  return `noch ~${Math.round(rest / 60)} min`;
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
        {pct}% {fmtRestzeit(p)}
      </span>
    </div>
  );
}
