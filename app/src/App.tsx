// Phase-0 gate: call `ping` on the Python sidecar through the Rust
// bridge and show whatever comes back. No styling polish yet — the
// success state is just "sidecar version appears on the window".

import { useEffect, useState } from "react";
import { call } from "./lib/rpc";
import type { PingResult } from "./lib/types";

type State =
  | { status: "pending" }
  | { status: "ok"; ping: PingResult }
  | { status: "error"; message: string };

export default function App() {
  const [state, setState] = useState<State>({ status: "pending" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const ping = await call<PingResult>("ping");
        if (!cancelled) setState({ status: "ok", ping });
      } catch (e) {
        if (!cancelled)
          setState({
            status: "error",
            message: e instanceof Error ? e.message : String(e),
          });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main
      style={{
        fontFamily: "var(--font-app)",
        background: "var(--bt-paper)",
        color: "var(--bt-ink)",
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        padding: 32,
      }}
    >
      <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600 }}>
        Blitztext — Phase 0
      </h1>

      {state.status === "pending" && (
        <p style={{ color: "var(--bt-muted-2)" }}>Pinging sidecar…</p>
      )}

      {state.status === "ok" && (
        <div
          style={{
            background: "var(--bt-white)",
            border: "1px solid var(--bt-line)",
            borderRadius: "var(--radius-xl)",
            padding: "16px 24px",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--fs-base)",
          }}
        >
          sidecar alive · v{state.ping.version}
        </div>
      )}

      {state.status === "error" && (
        <div
          style={{
            background: "var(--bt-red-bg)",
            color: "var(--bt-red-ink)",
            border: "1px solid var(--bt-red)",
            borderRadius: "var(--radius-xl)",
            padding: "12px 20px",
            maxWidth: 600,
            fontFamily: "var(--font-mono)",
            fontSize: "var(--fs-sm)",
          }}
        >
          sidecar error: {state.message}
        </div>
      )}

      <p
        style={{
          color: "var(--bt-subtle)",
          fontSize: "var(--fs-sm)",
          marginTop: "auto",
        }}
      >
        Meeting-Transkriptions-Modus · {new Date().toISOString().slice(0, 10)}
      </p>
    </main>
  );
}
