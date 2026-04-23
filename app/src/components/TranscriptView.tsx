// Middle column of MeetingReview: scrollable turn-by-turn transcript.
//
// For MVP we render all turns directly — typical meetings are <2000 turns
// which React handles fine. If we hit 10k+ turn meetings we swap in
// @tanstack/react-virtual here, but not yet.

import { AlertTriangle } from "lucide-react";
import { useMeetingStore } from "../state/useMeetingStore";
import type { Speaker, Turn } from "../lib/types";

function fmtTimestamp(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TranscriptView() {
  const active = useMeetingStore((s) => s.active);
  const useCleanup = useMeetingStore((s) => s.useCleanup);
  const loading = useMeetingStore((s) => s.activeLoading);
  const err = useMeetingStore((s) => s.activeError);

  if (loading) {
    return <Centered>Lade Transkript…</Centered>;
  }
  if (err) {
    return <Centered color="var(--bt-red-ink)">Fehler: {err}</Centered>;
  }
  if (!active) {
    return <Centered>Kein Meeting ausgewählt</Centered>;
  }
  if (active.turns.length === 0) {
    return (
      <Centered>
        Noch keine Turns — das Meeting hat {active.status === "processing" ? "die Verarbeitung noch nicht abgeschlossen" : "keinen Inhalt"}.
      </Centered>
    );
  }

  const speakersById = Object.fromEntries(active.speakers.map((s) => [s.id, s]));

  return (
    <div
      style={{
        height: "100%",
        overflowY: "auto",
        background: "var(--bt-white)",
      }}
    >
      <div
        style={{
          maxWidth: 820,
          margin: "0 auto",
          padding: "28px 32px 48px",
        }}
      >
        <TranscriptHeader title={active.title} />
        {active.turns.map((t, i) => (
          <TurnRow
            key={t.id}
            turn={t}
            speaker={speakersById[t.speaker_id]}
            useCleanup={useCleanup}
            firstOfSpeaker={
              i === 0 || active.turns[i - 1].speaker_id !== t.speaker_id
            }
          />
        ))}
      </div>
    </div>
  );
}

function TranscriptHeader({ title }: { title: string }) {
  const setTitle = useMeetingStore((s) => s.setTitle);
  return (
    <div style={{ marginBottom: 20 }}>
      <h1
        style={{ fontSize: "var(--fs-xl)", fontWeight: 600 }}
        contentEditable
        suppressContentEditableWarning
        onBlur={(e) => {
          const v = (e.currentTarget.textContent || "").trim();
          if (v && v !== title) void setTitle(v);
        }}
      >
        {title}
      </h1>
    </div>
  );
}

function TurnRow({
  turn,
  speaker,
  useCleanup,
  firstOfSpeaker,
}: {
  turn: Turn;
  speaker: Speaker | undefined;
  useCleanup: boolean;
  firstOfSpeaker: boolean;
}) {
  const color = speaker?.color || "var(--bt-muted-2)";
  const name = speaker?.name || speaker?.label || "Unbekannt";
  const text = (useCleanup && turn.text_clean) || turn.text_raw;
  const showCleanBadge = useCleanup && !!turn.text_clean;

  return (
    <div
      style={{
        padding: firstOfSpeaker ? "16px 0 8px" : "4px 0 8px",
        borderBottom: "1px solid var(--bt-line-soft)",
      }}
    >
      {firstOfSpeaker && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 6,
          }}
        >
          <span
            aria-hidden
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: color,
            }}
          />
          <span style={{ fontWeight: 600, fontSize: "var(--fs-md)" }}>
            {name}
          </span>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: "var(--fs-xs)",
              color: "var(--bt-subtle)",
            }}
          >
            {fmtTimestamp(turn.start_ms)}
          </span>
          {turn.overlap_flag && (
            <span
              title="Mehrere Sprecher überlappen hier — Zuordnung unsicher."
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: "var(--fs-xs)",
                color: "var(--bt-amber)",
              }}
            >
              <AlertTriangle size={11} /> überlappende Rede
            </span>
          )}
          {showCleanBadge && (
            <span
              title="Text durch LLM-Cleanup bereinigt."
              style={{
                fontSize: "var(--fs-xs)",
                color: "var(--bt-green)",
                fontFamily: "var(--font-mono)",
              }}
            >
              · bereinigt
            </span>
          )}
        </div>
      )}
      <p
        style={{
          fontSize: "var(--fs-base)",
          lineHeight: 1.65,
          color: "var(--bt-ink-soft)",
          marginLeft: firstOfSpeaker ? 18 : 18,
        }}
      >
        {text}
      </p>
    </div>
  );
}

function Centered({
  children,
  color,
}: {
  children: React.ReactNode;
  color?: string;
}) {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: color || "var(--bt-muted-2)",
        fontSize: "var(--fs-base)",
      }}
    >
      {children}
    </div>
  );
}
