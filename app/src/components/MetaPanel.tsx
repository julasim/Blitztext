// Right column of MeetingReview: metadata + actions (cleanup, export).

import { Download, FileText, Loader2, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import { call } from "../lib/rpc";
import { useMeetingStore } from "../state/useMeetingStore";

function fmtDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function MetaPanel() {
  const active = useMeetingStore((s) => s.active);
  const cleanupRunning = useMeetingStore((s) => s.cleanupRunning);
  const cleanupError = useMeetingStore((s) => s.cleanupError);
  const runCleanup = useMeetingStore((s) => s.runCleanup);
  const useCleanup = useMeetingStore((s) => s.useCleanup);
  const setUseCleanup = useMeetingStore((s) => s.setUseCleanup);
  const deleteMeeting = useMeetingStore((s) => s.deleteMeeting);
  const goLibrary = useMeetingStore((s) => s.goLibrary);

  if (!active) return null;

  const cleanedCount = active.turns.filter((t) => !!t.text_clean).length;
  const totalCount = active.turns.length;

  return (
    <div
      style={{
        width: 320,
        flexShrink: 0,
        background: "var(--bt-paper)",
        borderLeft: "1px solid var(--bt-line)",
        padding: "20px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 18,
        overflowY: "auto",
        height: "100%",
      }}
    >
      <Section label="Details">
        <Row label="Datum" value={fmtDate(active.created_at)} />
        <Row label="Dauer" value={fmtDuration(active.duration_ms)} />
        <Row label="Sprache" value={active.language?.toUpperCase() || "—"} />
        <Row label="Whisper" value={active.whisper_model || "—"} mono />
        <Row label="Sprecher" value={String(active.speakers.length)} />
        <Row label="Turns" value={String(active.turns.length)} />
      </Section>

      <Section label="LLM-Cleanup">
        <div style={{ fontSize: "var(--fs-sm)", color: "var(--bt-muted)", lineHeight: 1.5 }}>
          Entfernt Füllwörter und Stotter-Wiederholungen. Inhalt bleibt unverändert.
        </div>
        <div
          style={{
            marginTop: 10,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <button
            type="button"
            disabled={cleanupRunning}
            onClick={() => void runCleanup()}
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              padding: "8px 12px",
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-ink)",
              color: "var(--bt-white)",
              opacity: cleanupRunning ? 0.5 : 1,
              fontSize: "var(--fs-sm)",
              fontWeight: 500,
            }}
          >
            {cleanupRunning ? (
              <>
                <Loader2 size={14} className="bt-spin" />
                Läuft…
              </>
            ) : (
              <>
                <Sparkles size={14} />
                {cleanedCount > 0 ? "Erneut bereinigen" : "Bereinigen"}
              </>
            )}
          </button>
        </div>
        {cleanedCount > 0 && (
          <div
            style={{
              marginTop: 10,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: "var(--fs-sm)",
            }}
          >
            <label style={{ color: "var(--bt-muted)" }}>
              Bereinigt anzeigen
            </label>
            <Toggle
              checked={useCleanup}
              onChange={setUseCleanup}
              disabled={cleanedCount === 0}
            />
          </div>
        )}
        {cleanedCount > 0 && cleanedCount < totalCount && (
          <div style={{ marginTop: 6, fontSize: "var(--fs-xs)", color: "var(--bt-subtle)" }}>
            {cleanedCount} von {totalCount} Turns bereinigt
          </div>
        )}
        {cleanupError && (
          <div
            style={{
              marginTop: 10,
              fontSize: "var(--fs-xs)",
              color: "var(--bt-red-ink)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {cleanupError}
          </div>
        )}
      </Section>

      <Section label="Export">
        <ExportButton
          meetingId={active.id}
          useCleanup={useCleanup}
          label="Markdown"
          icon={<FileText size={14} />}
          extension="md"
        />
      </Section>

      <Section label="Gefahrenzone">
        <button
          type="button"
          onClick={async () => {
            if (
              confirm(
                `„${active.title}" und alle zugehörigen Daten wirklich löschen?`,
              )
            ) {
              await deleteMeeting(active.id);
              goLibrary();
            }
          }}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "8px 12px",
            borderRadius: "var(--radius-lg)",
            border: "1px solid var(--bt-red)",
            color: "var(--bt-red-ink)",
            background: "var(--bt-red-bg)",
            fontSize: "var(--fs-sm)",
          }}
        >
          <Trash2 size={14} />
          Meeting löschen
        </button>
      </Section>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div
        style={{
          fontSize: "var(--fs-xs)",
          fontWeight: 600,
          color: "var(--bt-subtle)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 10,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "6px 0",
        borderBottom: "1px solid var(--bt-line-soft)",
        fontSize: "var(--fs-sm)",
      }}
    >
      <span style={{ color: "var(--bt-muted-2)" }}>{label}</span>
      <span
        style={{
          color: "var(--bt-ink-soft)",
          fontFamily: mono ? "var(--font-mono)" : "inherit",
          fontSize: mono ? "var(--fs-xs)" : "inherit",
        }}
      >
        {value}
      </span>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        width: 34,
        height: 20,
        borderRadius: 10,
        background: checked ? "var(--bt-ink)" : "var(--bt-line)",
        position: "relative",
        transition: "background 120ms ease",
        flexShrink: 0,
        opacity: disabled ? 0.4 : 1,
      }}
    >
      <span
        style={{
          position: "absolute",
          top: 2,
          left: checked ? 16 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "var(--bt-white)",
          transition: "left 120ms ease",
          boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
        }}
      />
    </button>
  );
}

function ExportButton({
  meetingId,
  useCleanup,
  label,
  icon,
  extension,
}: {
  meetingId: string;
  useCleanup: boolean;
  label: string;
  icon: React.ReactNode;
  extension: string;
}) {
  const [state, setState] = useState<"idle" | "running" | "done" | "error">(
    "idle",
  );
  const [message, setMessage] = useState("");

  const click = async () => {
    setState("running");
    setMessage("");
    try {
      // Lazy-import to avoid pulling the dialog plugin at module load.
      const { save } = await import("@tauri-apps/plugin-dialog");
      const path = await save({
        defaultPath: `meeting.${extension}`,
        filters: [{ name: label, extensions: [extension] }],
      });
      if (!path) {
        setState("idle");
        return;
      }
      const result = await call<{ ok: boolean; bytes: number; path: string }>(
        "export.markdown",
        {
          meeting_id: meetingId,
          path,
          use_cleanup: useCleanup,
        },
      );
      setMessage(`${Math.round(result.bytes / 1024)} KB`);
      setState("done");
      setTimeout(() => setState("idle"), 2000);
    } catch (e) {
      setState("error");
      setMessage(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <button
      type="button"
      onClick={click}
      disabled={state === "running"}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        borderRadius: "var(--radius-lg)",
        border: "1px solid var(--bt-line)",
        background: "var(--bt-white)",
        color: "var(--bt-ink-soft)",
        fontSize: "var(--fs-sm)",
        width: "100%",
      }}
    >
      {icon}
      <span style={{ flex: 1, textAlign: "left" }}>{label}</span>
      {state === "running" && <Loader2 size={12} className="bt-spin" />}
      {state === "done" && (
        <span style={{ color: "var(--bt-green)", fontSize: "var(--fs-xs)" }}>
          {message}
        </span>
      )}
      {state === "error" && (
        <span
          style={{
            color: "var(--bt-red-ink)",
            fontSize: "var(--fs-xs)",
          }}
          title={message}
        >
          Fehler
        </span>
      )}
      {state === "idle" && <Download size={12} style={{ opacity: 0.5 }} />}
    </button>
  );
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("de-AT", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
