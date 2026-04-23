// Persistent left sidebar: navigation + meeting list.
//
// Design pulls directly from the handoff MainApp sidebar — 280px wide,
// light-paper background, thin right border, section headers, nav links,
// meeting list with tag colors. Simplified from the prototype (no search
// yet, no dictation history mixed in — will come in Phase 2).

import { FileAudio, Plus, Settings as SettingsIcon, Zap } from "lucide-react";
import { useMeetingStore } from "../state/useMeetingStore";
import type { MeetingListItem } from "../lib/types";

const dotColors = [
  "#09090b",
  "#ef4444",
  "#f59e0b",
  "#10b981",
  "#3b82f6",
  "#8b5cf6",
  "#ec4899",
  "#14b8a6",
];

function dotColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return dotColors[h % dotColors.length];
}

function fmtDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("de-AT", {
      day: "2-digit",
      month: "short",
    });
  } catch {
    return "";
  }
}

export function Sidebar() {
  const view = useMeetingStore((s) => s.view);
  const goLibrary = useMeetingStore((s) => s.goLibrary);
  const goImport = useMeetingStore((s) => s.goImport);
  const goReview = useMeetingStore((s) => s.goReview);
  const goSettings = useMeetingStore((s) => s.goSettings);
  const meetings = useMeetingStore((s) => s.meetings);
  const loading = useMeetingStore((s) => s.meetingsLoading);
  const err = useMeetingStore((s) => s.meetingsError);

  const activeId = view.name === "review" ? view.meetingId : null;

  return (
    <aside
      style={{
        width: 280,
        flexShrink: 0,
        background: "var(--bt-paper)",
        borderRight: "1px solid var(--bt-line)",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
    >
      {/* Header / brand */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "14px 16px",
          borderBottom: "1px solid var(--bt-line)",
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: "var(--bt-ink)",
            color: "var(--bt-white)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          aria-hidden
        >
          <Zap size={16} strokeWidth={2.2} fill="currentColor" />
        </div>
        <div>
          <div
            style={{
              fontWeight: 600,
              fontSize: "var(--fs-md)",
              lineHeight: 1.1,
            }}
          >
            Blitztext
          </div>
          <div
            style={{
              fontSize: "var(--fs-xs)",
              color: "var(--bt-subtle)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              marginTop: 2,
            }}
          >
            Meeting Mode
          </div>
        </div>
      </div>

      {/* Primary action */}
      <div style={{ padding: "14px 14px 8px" }}>
        <button
          type="button"
          onClick={goImport}
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 12px",
            borderRadius: "var(--radius-lg)",
            background: "var(--bt-ink)",
            color: "var(--bt-white)",
            fontSize: "var(--fs-base)",
            fontWeight: 500,
          }}
        >
          <Plus size={16} strokeWidth={2} />
          Neues Meeting
        </button>
      </div>

      {/* Meeting list */}
      <div style={{ padding: "4px 8px", flex: 1, overflowY: "auto" }}>
        <div
          style={{
            padding: "10px 10px 6px",
            fontSize: "var(--fs-xs)",
            fontWeight: 600,
            color: "var(--bt-subtle)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Aufnahmen
        </div>

        {loading && (
          <div style={{ padding: "6px 10px", color: "var(--bt-subtle)", fontSize: "var(--fs-sm)" }}>
            Lade…
          </div>
        )}
        {err && (
          <div style={{ padding: "6px 10px", color: "var(--bt-red-ink)", fontSize: "var(--fs-sm)" }}>
            {err}
          </div>
        )}
        {!loading && !err && meetings.length === 0 && (
          <div
            style={{
              padding: "12px 10px",
              color: "var(--bt-subtle)",
              fontSize: "var(--fs-sm)",
              lineHeight: 1.5,
            }}
          >
            Noch keine Meetings. Starte mit einem Import oben.
          </div>
        )}
        {meetings.map((m) => (
          <MeetingRow
            key={m.id}
            m={m}
            active={m.id === activeId}
            onClick={() => goReview(m.id)}
          />
        ))}
      </div>

      {/* Footer nav */}
      <div
        style={{
          borderTop: "1px solid var(--bt-line)",
          padding: "8px 10px",
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}
      >
        <NavLink
          active={view.name === "library"}
          onClick={goLibrary}
          icon={<FileAudio size={14} strokeWidth={1.6} />}
          label="Bibliothek"
        />
        <NavLink
          active={view.name === "settings"}
          onClick={goSettings}
          icon={<SettingsIcon size={14} strokeWidth={1.6} />}
          label="Einstellungen"
        />
      </div>
    </aside>
  );
}

function MeetingRow({
  m,
  active,
  onClick,
}: {
  m: MeetingListItem;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "8px 10px",
        margin: "1px 0",
        borderRadius: "var(--radius-lg)",
        background: active ? "var(--bt-stone)" : "transparent",
        color: active ? "var(--bt-ink)" : "var(--bt-muted)",
        fontSize: "var(--fs-base)",
        textAlign: "left",
        borderLeft: active ? "3px solid var(--bt-ink)" : "3px solid transparent",
        paddingLeft: active ? 7 : 10,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: dotColor(m.id),
          flexShrink: 0,
        }}
      />
      <span
        style={{
          flex: 1,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          fontWeight: active ? 500 : 400,
        }}
      >
        {m.title}
      </span>
      <span
        style={{
          fontSize: "var(--fs-xs)",
          fontFamily: "var(--font-mono)",
          color: "var(--bt-subtle)",
          flexShrink: 0,
        }}
        title={fmtDate(m.created_at)}
      >
        {fmtDuration(m.duration_ms)}
      </span>
    </button>
  );
}

function NavLink({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 10px",
        borderRadius: "var(--radius-lg)",
        background: active ? "var(--bt-stone)" : "transparent",
        color: active ? "var(--bt-ink)" : "var(--bt-muted)",
        fontSize: "var(--fs-base)",
        textAlign: "left",
        width: "100%",
      }}
    >
      {icon}
      {label}
    </button>
  );
}
