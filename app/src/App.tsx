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
  const loadJobs = useMeetingStore((s) => s.loadJobs);
  const wireSidecarEvents = useMeetingStore((s) => s.wireSidecarEvents);

  useEffect(() => {
    let cancelled = false;
    let unwire: (() => void) | null = null;
    (async () => {
      try {
        const ping = await call<{ ok: boolean; version: string }>("ping");
        if (cancelled) return;
        setBoot({ status: "ok", version: ping.version });
        const off = await wireSidecarEvents();
        // Zwischen dem Start dieses Effects und hier liegen zwei await. Lief
        // die Aufräumfunktion in der Zwischenzeit, war `unwire` dort noch
        // null und die Listener blieben für immer hängen — unter StrictMode
        // (Doppel-Mount im Dev-Modus) also sieben Abonnements zweimal, mit
        // doppelt verarbeiteten Events.
        if (cancelled) {
          off();
          return;
        }
        unwire = off;
        await Promise.all([loadConfig(), loadMeetings(), loadJobs()]);
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
  }, [loadConfig, loadMeetings, loadJobs, wireSidecarEvents]);

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
      <ActionErrorBanner />
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

/** Meldung einer fehlgeschlagenen Aktion (Löschen, Umbenennen, Abbrechen).
 *
 * Diese Pfade scheiterten vorher **stumm**: der Nutzer klickte, nichts
 * geschah, und nichts erklärte warum. Die Leiste steht bewusst oben über
 * allen Ansichten — der Fehler kann in jeder von ihnen ausgelöst werden. */
function ActionErrorBanner() {
  const message = useMeetingStore((s) => s.actionError);
  const clear = useMeetingStore((s) => s.clearActionError);
  if (!message) return null;
  return (
    <div
      role="alert"
      style={{
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 14px",
        borderBottom: "1px solid var(--bt-red)",
        background: "var(--bt-red-bg)",
        color: "var(--bt-red-ink)",
        fontSize: "var(--fs-sm)",
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>{message}</span>
      <button
        type="button"
        onClick={clear}
        aria-label="Meldung schließen"
        style={{
          border: "none",
          background: "transparent",
          color: "inherit",
          cursor: "pointer",
          fontSize: "var(--fs-md)",
          lineHeight: 1,
          padding: 2,
        }}
      >
        ×
      </button>
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
