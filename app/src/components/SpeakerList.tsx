// Left column of the MeetingReview: clickable speaker chips with
// percentage-of-airtime and word count. Clicking opens a rename popover
// (a modal for now — we'll switch to a real popover once we care about
// positioning details).

import { Users } from "lucide-react";
import { useState } from "react";
import { useMeetingStore } from "../state/useMeetingStore";
import type { Speaker } from "../lib/types";

export function SpeakerList() {
  const active = useMeetingStore((s) => s.active);
  const renameSpeaker = useMeetingStore((s) => s.renameSpeaker);
  const mergeSpeakers = useMeetingStore((s) => s.mergeSpeakers);
  const [editing, setEditing] = useState<Speaker | null>(null);

  if (!active) return null;
  const total = active.duration_ms || 1;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        borderRight: "1px solid var(--bt-line)",
        background: "var(--bt-white)",
      }}
    >
      <Header count={active.speakers.length} />
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 12px" }}>
        {active.speakers.map((sp) => (
          <SpeakerRow
            key={sp.id}
            sp={sp}
            totalMs={total}
            onClick={() => setEditing(sp)}
          />
        ))}
      </div>

      {editing && (
        <RenameModal
          speaker={editing}
          otherSpeakers={active.speakers.filter((s) => s.id !== editing.id)}
          onClose={() => setEditing(null)}
          onRename={async (name) => {
            await renameSpeaker(editing.id, name);
            setEditing(null);
          }}
          onMergeInto={async (targetId) => {
            await mergeSpeakers(editing.id, targetId);
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

function Header({ count }: { count: number }) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderBottom: "1px solid var(--bt-line)",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <Users size={14} strokeWidth={1.6} />
      <div style={{ fontSize: "var(--fs-md)", fontWeight: 600 }}>Sprecher</div>
      <div
        style={{
          marginLeft: "auto",
          fontSize: "var(--fs-xs)",
          color: "var(--bt-subtle)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {count}
      </div>
    </div>
  );
}

function SpeakerRow({
  sp,
  totalMs,
  onClick,
}: {
  sp: Speaker;
  totalMs: number;
  onClick: () => void;
}) {
  const name = sp.name || sp.label;
  const unnamed = !sp.name;
  const pct = sp.share_pct ?? Math.round((100 * sp.duration_ms) / totalMs);

  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "10px 12px",
        margin: "4px 0",
        borderRadius: "var(--radius-lg)",
        border: "1px solid var(--bt-line)",
        background: "var(--bt-white)",
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          aria-hidden
          style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: sp.color,
            flexShrink: 0,
          }}
        />
        <span
          style={{
            flex: 1,
            fontWeight: unnamed ? 400 : 500,
            color: unnamed ? "var(--bt-muted-2)" : "var(--bt-ink)",
            fontStyle: unnamed ? "italic" : "normal",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {name}
        </span>
        <span
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {pct}%
        </span>
      </div>
      {/* Progress bar */}
      <div
        style={{
          marginTop: 8,
          height: 3,
          borderRadius: 2,
          background: "var(--bt-line-soft)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: sp.color,
            transition: "width 200ms ease",
          }}
        />
      </div>
      <div
        style={{
          marginTop: 6,
          display: "flex",
          gap: 10,
          fontSize: "var(--fs-xs)",
          color: "var(--bt-subtle)",
        }}
      >
        <span>{sp.word_count} Wörter</span>
        <span>•</span>
        <span>{fmtDuration(sp.duration_ms)}</span>
      </div>
    </button>
  );
}

function fmtDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m} min ${String(s % 60).padStart(2, "0")}s`;
}

function RenameModal({
  speaker,
  otherSpeakers,
  onClose,
  onRename,
  onMergeInto,
}: {
  speaker: Speaker;
  otherSpeakers: Speaker[];
  onClose: () => void;
  onRename: (name: string) => Promise<void>;
  onMergeInto: (targetId: string) => Promise<void>;
}) {
  const [name, setName] = useState(speaker.name || "");
  const [busy, setBusy] = useState(false);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.3)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 420,
          background: "var(--bt-white)",
          borderRadius: "var(--radius-2xl)",
          boxShadow: "var(--shadow-float)",
          padding: 20,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            aria-hidden
            style={{
              width: 14,
              height: 14,
              borderRadius: "50%",
              background: speaker.color,
            }}
          />
          <div style={{ fontSize: "var(--fs-lg)", fontWeight: 600 }}>
            Sprecher umbenennen
          </div>
        </div>
        <div
          style={{
            fontSize: "var(--fs-sm)",
            color: "var(--bt-muted-2)",
          }}
        >
          Aktuell: <strong>{speaker.name || speaker.label}</strong> —{" "}
          {speaker.word_count} Wörter, {speaker.share_pct}% Redeanteil
        </div>

        <label
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--bt-muted-2)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            fontWeight: 600,
          }}
        >
          Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          placeholder="z. B. Julius Sima"
          style={{
            padding: "10px 12px",
            border: "1px solid var(--bt-line)",
            borderRadius: "var(--radius-lg)",
            background: "var(--bt-white)",
            fontSize: "var(--fs-base)",
          }}
          onKeyDown={async (e) => {
            if (e.key === "Enter" && name.trim()) {
              setBusy(true);
              await onRename(name.trim());
              setBusy(false);
            }
          }}
        />

        {otherSpeakers.length > 0 && (
          <>
            <label
              style={{
                fontSize: "var(--fs-xs)",
                color: "var(--bt-muted-2)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                fontWeight: 600,
                marginTop: 6,
              }}
            >
              Oder mit anderem Sprecher zusammenfassen
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {otherSpeakers.map((o) => (
                <button
                  key={o.id}
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    await onMergeInto(o.id);
                    setBusy(false);
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 10px",
                    border: "1px solid var(--bt-line)",
                    borderRadius: "var(--radius-lg)",
                    background: "var(--bt-paper)",
                    fontSize: "var(--fs-sm)",
                  }}
                >
                  <span
                    aria-hidden
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: o.color,
                    }}
                  />
                  → {o.name || o.label}
                </button>
              ))}
            </div>
          </>
        )}

        <div
          style={{
            marginTop: 8,
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
          }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            style={{
              padding: "8px 14px",
              border: "1px solid var(--bt-line)",
              borderRadius: "var(--radius-lg)",
              color: "var(--bt-muted)",
              background: "var(--bt-white)",
            }}
          >
            Abbrechen
          </button>
          <button
            type="button"
            onClick={async () => {
              setBusy(true);
              await onRename(name.trim());
              setBusy(false);
            }}
            disabled={busy || !name.trim()}
            style={{
              padding: "8px 14px",
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-ink)",
              color: "var(--bt-white)",
              opacity: busy || !name.trim() ? 0.5 : 1,
            }}
          >
            {busy ? "Speichere…" : "Speichern"}
          </button>
        </div>
      </div>
    </div>
  );
}
