// Floating recorder widget — runs in the dedicated 'mini' Tauri window.
//
// Single screen, two states: idle (mic-button to start) and recording
// (live timer + waveform + stop). Pure UI; the real work happens in
// recording.start / recording.stop on the sidecar.

import { Home, Mic, MoreHorizontal, Pause, Play, Square, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { call, onEvent } from "../lib/rpc";

const SAMPLE_RATE = 16_000;

type RecState =
  | { name: "idle" }
  | { name: "starting" }
  | { name: "recording"; meeting_id: string; startedAt: number; paused: boolean }
  | { name: "stopping" }
  | { name: "error"; message: string };

export function MiniWidget() {
  const [state, setState] = useState<RecState>({ name: "idle" });
  const [now, setNow] = useState(() => Date.now());
  const [menuOpen, setMenuOpen] = useState(false);
  const [pauseStartedAt, setPauseStartedAt] = useState<number | null>(null);
  const [accumulatedPauseMs, setAccumulatedPauseMs] = useState(0);

  // Tick the clock once a second while recording so the timer keeps moving.
  const tickerRunning = state.name === "recording" && !state.paused;
  useEffect(() => {
    if (!tickerRunning) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [tickerRunning]);

  // Sync to recording.* events: useful if the sidecar starts/stops via
  // a different surface (global shortcut, tray) while the widget is open.
  useEffect(() => {
    const offs: Array<() => void> = [];
    (async () => {
      offs.push(
        await onEvent<{ meeting_id: string; title?: string }>(
          "recording.started",
          (p) =>
            setState({
              name: "recording",
              meeting_id: p.meeting_id,
              startedAt: Date.now(),
              paused: false,
            }),
        ),
        await onEvent<{ meeting_id: string }>("recording.stopped", () => {
          setState({ name: "idle" });
          // Auto-close the widget after a stop — main window takes over.
          void closeMiniWindow();
        }),
        await onEvent<{ meeting_id: string }>("recording.cancelled", () => {
          setState({ name: "idle" });
          void closeMiniWindow();
        }),
        await onEvent<{ meeting_id: string }>("recording.paused", () => {
          setState((s) => (s.name === "recording" ? { ...s, paused: true } : s));
          setPauseStartedAt(Date.now());
        }),
        await onEvent<{ meeting_id: string }>("recording.resumed", () => {
          setState((s) =>
            s.name === "recording" ? { ...s, paused: false } : s,
          );
          setPauseStartedAt((startedAt) => {
            if (startedAt !== null) {
              setAccumulatedPauseMs((ms) => ms + (Date.now() - startedAt));
            }
            return null;
          });
        }),
      );
    })();
    return () => {
      for (const off of offs) off();
    };
  }, []);

  // Subtract pause time so the timer reflects only actively-recorded
  // seconds, not wall-clock since start.
  const elapsedSec =
    state.name === "recording"
      ? Math.max(
          0,
          Math.floor(
            (now -
              state.startedAt -
              accumulatedPauseMs -
              (state.paused && pauseStartedAt !== null
                ? now - pauseStartedAt
                : 0)) /
              1000,
          ),
        )
      : 0;

  const start = async () => {
    setState({ name: "starting" });
    try {
      const r = await call<{ meeting_id: string }>("recording.start", {});
      setState({
        name: "recording",
        meeting_id: r.meeting_id,
        startedAt: Date.now(),
        paused: false,
      });
    } catch (e) {
      setState({
        name: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const stop = async () => {
    setState({ name: "stopping" });
    try {
      await call("recording.stop");
      // recording.stopped event will reset state and close the window.
    } catch (e) {
      setState({
        name: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const cancel = async () => {
    try {
      await call("recording.cancel");
    } catch {
      /* ignore — we close anyway */
    }
    void closeMiniWindow();
  };

  const togglePause = async () => {
    if (state.name !== "recording") return;
    try {
      await call(state.paused ? "recording.resume" : "recording.pause");
      // Local state will be updated by the recording.paused / .resumed event.
    } catch (e) {
      console.error("toggle pause failed:", e);
    }
  };

  const openMainWindow = async () => {
    setMenuOpen(false);
    try {
      const { Window } = await import("@tauri-apps/api/window");
      const main = await Window.getByLabel("main");
      if (main) {
        await main.show();
        await main.unminimize();
        await main.setFocus();
      }
    } catch (e) {
      console.error("open main failed:", e);
    }
  };

  return (
    <div
      style={{
        // The widget body is rounded; the OS window is transparent so this
        // shape is what the user sees.
        width: "100vw",
        height: "100vh",
        background: "var(--bt-white)",
        border: "1px solid var(--bt-line)",
        borderRadius: "var(--radius-2xl)",
        boxShadow: "var(--shadow-float)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        userSelect: "none",
      }}
    >
      {/* Drag handle — Tauri picks up data-tauri-drag-region for moving
          a frameless window with the mouse. */}
      <div
        data-tauri-drag-region
        style={{
          padding: "8px 0 4px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: 56,
            height: 4,
            borderRadius: 2,
            background: "var(--bt-line)",
            pointerEvents: "none",
          }}
        />
      </div>

      <div
        style={{
          padding: "0 16px 4px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: "var(--fs-sm)",
            color: "var(--bt-muted)",
          }}
        >
          {state.name === "recording" && !state.paused && (
            <span
              aria-hidden
              className="bt-pulse"
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "var(--bt-red)",
              }}
            />
          )}
          {state.name === "recording" ? "Aufnahme" : "Blitztext"}
        </div>
        <button
          type="button"
          onClick={state.name === "recording" || state.name === "starting" ? cancel : closeMiniWindow}
          style={iconBtn()}
          aria-label="Schließen"
        >
          <X size={12} />
        </button>
      </div>

      <Timer seconds={elapsedSec} />

      <Waveform recording={state.name === "recording" && !state.paused} />

      <div
        style={{
          padding: "10px 16px 12px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 14,
          position: "relative",
        }}
      >
        {state.name === "recording" && (
          <button
            type="button"
            onClick={togglePause}
            style={iconBtn(36)}
            title={state.paused ? "Fortsetzen" : "Pause"}
            aria-label={state.paused ? "Fortsetzen" : "Pause"}
          >
            {state.paused ? (
              <Play size={14} fill="currentColor" strokeWidth={0} />
            ) : (
              <Pause size={14} fill="currentColor" strokeWidth={0} />
            )}
          </button>
        )}
        {state.name === "idle" || state.name === "starting" ? (
          <button
            type="button"
            onClick={start}
            disabled={state.name === "starting"}
            style={recordBtn(state.name === "starting")}
            aria-label="Aufnahme starten"
          >
            <Mic size={20} strokeWidth={2.2} />
          </button>
        ) : (
          <button
            type="button"
            onClick={stop}
            disabled={state.name === "stopping"}
            style={recordBtn(state.name === "stopping", true)}
            aria-label="Stoppen"
          >
            <Square size={16} fill="currentColor" strokeWidth={0} />
          </button>
        )}
        {state.name === "recording" && (
          <>
            <button
              type="button"
              onClick={() => setMenuOpen((o) => !o)}
              style={iconBtn(36)}
              title="Mehr"
              aria-label="Mehr"
            >
              <MoreHorizontal size={16} />
            </button>
            {menuOpen && <MoreMenu onOpenMain={openMainWindow} onCancel={cancel} onClose={() => setMenuOpen(false)} />}
          </>
        )}
      </div>

      {state.name === "error" && (
        <div
          style={{
            position: "absolute",
            bottom: 4,
            left: 12,
            right: 12,
            fontSize: "var(--fs-xs)",
            color: "var(--bt-red-ink)",
            background: "var(--bt-red-bg)",
            padding: "4px 8px",
            borderRadius: 4,
            fontFamily: "var(--font-mono)",
          }}
          title={state.message}
        >
          {state.message.slice(0, 80)}
        </div>
      )}
    </div>
  );
}

function MoreMenu({
  onOpenMain,
  onCancel,
  onClose,
}: {
  onOpenMain: () => void;
  onCancel: () => void;
  onClose: () => void;
}) {
  // Click-outside to close.
  useEffect(() => {
    const onDocClick = () => onClose();
    const t = window.setTimeout(
      () => document.addEventListener("click", onDocClick, { once: true }),
      0,
    );
    return () => {
      window.clearTimeout(t);
      document.removeEventListener("click", onDocClick);
    };
  }, [onClose]);

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        position: "absolute",
        right: 16,
        bottom: 56,
        minWidth: 200,
        background: "var(--bt-white)",
        border: "1px solid var(--bt-line)",
        borderRadius: "var(--radius-lg)",
        boxShadow: "var(--shadow-panel)",
        padding: 4,
        zIndex: 10,
      }}
    >
      <MenuItem onClick={onOpenMain} icon={<Home size={14} />}>
        Hauptfenster öffnen
      </MenuItem>
      <MenuItem onClick={onCancel} icon={<Trash2 size={14} />} danger>
        Aufnahme verwerfen
      </MenuItem>
    </div>
  );
}

function MenuItem({
  onClick,
  icon,
  danger,
  children,
}: {
  onClick: () => void;
  icon: React.ReactNode;
  danger?: boolean;
  children: React.ReactNode;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "8px 10px",
        borderRadius: "var(--radius-sm)",
        background: hover ? "var(--bt-paper-2)" : "transparent",
        color: danger ? "var(--bt-red-ink)" : "var(--bt-ink-soft)",
        fontSize: "var(--fs-sm)",
        textAlign: "left",
      }}
    >
      <span style={{ color: danger ? "var(--bt-red)" : "var(--bt-muted-2)" }}>
        {icon}
      </span>
      {children}
    </button>
  );
}

function Timer({ seconds }: { seconds: number }) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return (
    <div
      style={{
        textAlign: "center",
        fontFamily: "var(--font-mono)",
        fontSize: 28,
        fontWeight: 500,
        color: "var(--bt-ink)",
        fontVariantNumeric: "tabular-nums",
        padding: "0 0 4px",
        letterSpacing: 0.5,
      }}
    >
      {String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
    </div>
  );
}

// --- Waveform: 44 bars, animated when recording, flat when idle. ---------

const BARS = 44;

function Waveform({ recording }: { recording: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const phasesRef = useRef<number[] | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (phasesRef.current === null) {
      phasesRef.current = Array.from({ length: BARS }, (_, i) => i * 0.37);
    }
    let running = true;
    const tick = (t: number) => {
      if (!running || !ref.current) return;
      const phases = phasesRef.current!;
      const ms = t / 1000;
      const children = ref.current.children as HTMLCollectionOf<HTMLElement>;
      for (let i = 0; i < BARS; i++) {
        if (!recording) {
          children[i].style.height = "3px";
          continue;
        }
        const a = Math.sin(ms * 4 + phases[i]);
        const b = Math.sin(ms * 6.7 + phases[i] * 0.6);
        const amp = (a + b * 0.6 + 1.5) / 2.5; // 0..1-ish
        const height = 3 + Math.max(0, amp) * 30;
        children[i].style.height = `${height}px`;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    return () => {
      running = false;
    };
  }, [recording]);

  return (
    <div
      ref={ref}
      style={{
        margin: "0 16px",
        height: 36,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
      }}
    >
      {Array.from({ length: BARS }).map((_, i) => (
        <span
          key={i}
          style={{
            display: "inline-block",
            width: 2,
            height: 3,
            background: "var(--bt-ink)",
            borderRadius: 1,
            transition: "height 80ms ease-out",
          }}
        />
      ))}
    </div>
  );
}

// --- Helpers --------------------------------------------------------------

async function closeMiniWindow() {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().hide();
  } catch {
    /* ignore */
  }
}

function iconBtn(size = 24): React.CSSProperties {
  return {
    width: size,
    height: size,
    borderRadius: 6,
    border: "1px solid var(--bt-line)",
    background: "var(--bt-white)",
    color: "var(--bt-muted)",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
  };
}

function recordBtn(busy: boolean, stopping = false): React.CSSProperties {
  return {
    width: 56,
    height: 56,
    borderRadius: "50%",
    background: "var(--bt-red)",
    color: "var(--bt-white)",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    boxShadow: stopping
      ? "0 0 0 6px rgba(220,38,38,0.18)"
      : "0 4px 14px rgba(220,38,38,0.30)",
    opacity: busy ? 0.6 : 1,
    cursor: busy ? "wait" : "pointer",
  };
}

// SAMPLE_RATE export so future frequency-domain visualization can sync;
// also keeps the import linter happy if we add it later.
void SAMPLE_RATE;
