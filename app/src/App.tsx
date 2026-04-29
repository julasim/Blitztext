// Root of the React app. Sidebar is always mounted; the right-hand
// surface renders the current view from useMeetingStore.view.
//
// On mount we pull config + the meeting list from the sidecar. If the
// sidecar isn't reachable (Python process crashed, not spawned yet), we
// show a blocking banner so the user knows what's wrong — the rest of
// the app won't function anyway.

import { useEffect, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { Titlebar } from "./components/Titlebar";
import { call } from "./lib/rpc";
import { useMeetingStore } from "./state/useMeetingStore";
import { Library } from "./views/Library";
import { MeetingImport } from "./views/MeetingImport";
import { MeetingReview } from "./views/MeetingReview";
import { Settings } from "./views/Settings";

type Boot =
  | { status: "pending" }
  | { status: "ok"; version: string }
  | { status: "error"; message: string };

export default function App() {
  const [boot, setBoot] = useState<Boot>({ status: "pending" });
  const view = useMeetingStore((s) => s.view);
  const loadConfig = useMeetingStore((s) => s.loadConfig);
  const loadMeetings = useMeetingStore((s) => s.loadMeetings);
  const wireSidecarEvents = useMeetingStore((s) => s.wireSidecarEvents);

  useEffect(() => {
    let cancelled = false;
    let unwire: (() => void) | null = null;
    (async () => {
      try {
        const ping = await call<{ ok: boolean; version: string }>("ping");
        if (cancelled) return;
        setBoot({ status: "ok", version: ping.version });
        unwire = await wireSidecarEvents();
        await Promise.all([loadConfig(), loadMeetings()]);
      } catch (e) {
        if (!cancelled) {
          setBoot({
            status: "error",
            message: e instanceof Error ? e.message : String(e),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
      if (unwire) unwire();
    };
  }, [loadConfig, loadMeetings, wireSidecarEvents]);

  // Subscribe to global-shortcut events emitted by Rust.
  // toggle_recording → handled by Rust directly (mini-widget toggle).
  // toggle_dictate → fire dictate.toggle on the sidecar so dictate works
  //   even when the main window isn't focused.
  useEffect(() => {
    const offs: Array<() => void> = [];
    (async () => {
      const { listen } = await import("@tauri-apps/api/event");
      const { onEvent } = await import("./lib/rpc");

      offs.push(
        await listen<{ action: string }>("bt://shortcut", (evt) => {
          if (evt.payload.action === "toggle_dictate") {
            void call("dictate.toggle").catch((e) =>
              console.warn("[dictate.toggle] failed:", e),
            );
            return;
          }
          console.info("[bt://shortcut]", evt.payload);
        }),
      );

      // Subtle dictate toasts so the user knows what happened — there's
      // no UI surface for dictate, only the shortcut.
      offs.push(
        await onEvent("dictate.started", () =>
          void notifyDictate("Diktieren läuft", "Sprich, dann Strg+Alt+1 erneut zum Stoppen."),
        ),
        await onEvent<{ text: string; injected: boolean }>(
          "dictate.done",
          (p) => {
            if (p.injected) {
              void notifyDictate(
                "Diktiert",
                `${p.text.split(/\s+/).filter(Boolean).length} Wörter eingefügt`,
              );
            }
          },
        ),
        await onEvent<{ stage: string; message: string }>(
          "dictate.error",
          (p) =>
            void notifyDictate(
              "Diktier-Fehler",
              `${p.stage}: ${p.message}`.slice(0, 200),
            ),
        ),
      );
    })();
    return () => {
      for (const off of offs) off();
    };
  }, []);

  if (boot.status === "error") {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          background: "var(--bt-white)",
        }}
      >
        <Titlebar />
        <SidecarErrorBanner message={boot.message} />
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--bt-white)",
      }}
    >
      <Titlebar />
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <Sidebar />
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          background: "var(--bt-white)",
        }}
      >
        {boot.status === "pending" ? (
          <BootingScreen />
        ) : view.name === "library" ? (
          <Library />
        ) : view.name === "import" ? (
          <MeetingImport />
        ) : view.name === "review" ? (
          <MeetingReview />
        ) : view.name === "settings" ? (
          <Settings />
        ) : null}
        {boot.status === "ok" && <StatusBar version={boot.version} />}
      </div>
      </div>
    </div>
  );
}

function BootingScreen() {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--bt-muted-2)",
      }}
    >
      Starte Sidecar…
    </div>
  );
}

function StatusBar({ version }: { version: string }) {
  const cfg = useMeetingStore((s) => s.config);
  return (
    <div
      style={{
        flexShrink: 0,
        height: 28,
        borderTop: "1px solid var(--bt-line)",
        background: "var(--bt-paper)",
        display: "flex",
        alignItems: "center",
        padding: "0 12px",
        gap: 16,
        fontSize: "var(--fs-xs)",
        color: "var(--bt-subtle)",
        fontFamily: "var(--font-mono)",
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--bt-green)",
          }}
        />
        sidecar v{version}
      </span>
      {cfg && (
        <>
          <span>GPU {cfg.cuda_available ? "✓" : "—"}</span>
          <span>Ollama {cfg.ollama_available ? "✓" : "—"}</span>
        </>
      )}
      <span style={{ marginLeft: "auto" }}>
        Lokal · keine Cloud
      </span>
    </div>
  );
}

async function notifyDictate(title: string, body: string): Promise<void> {
  try {
    const { isPermissionGranted, requestPermission, sendNotification } =
      await import("@tauri-apps/plugin-notification");
    let granted = await isPermissionGranted();
    if (!granted) {
      const r = await requestPermission();
      granted = r === "granted";
    }
    if (!granted) return;
    sendNotification({ title, body });
  } catch (e) {
    console.warn("[notify dictate] failed:", e);
  }
}

function SidecarErrorBanner({ message }: { message: string }) {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
      }}
    >
      <div
        style={{
          maxWidth: 520,
          padding: 24,
          borderRadius: "var(--radius-2xl)",
          border: "1px solid var(--bt-red)",
          background: "var(--bt-red-bg)",
          color: "var(--bt-red-ink)",
        }}
      >
        <div style={{ fontSize: "var(--fs-lg)", fontWeight: 600, marginBottom: 10 }}>
          Sidecar nicht erreichbar
        </div>
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--fs-sm)",
            lineHeight: 1.6,
            color: "var(--bt-red-ink)",
          }}
        >
          {message}
        </p>
        <p
          style={{
            marginTop: 14,
            fontSize: "var(--fs-sm)",
            color: "var(--bt-muted)",
            lineHeight: 1.6,
          }}
        >
          Der Python-Prozess hat sich nicht gestartet oder wurde getötet.
          Starte Blitztext neu. Wenn der Fehler bleibt, schau in den Sidecar-Log
          unter <code>%APPDATA%\Blitztext\sidecar.log</code>.
        </p>
      </div>
    </div>
  );
}
