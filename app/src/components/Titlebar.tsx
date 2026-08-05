// Custom Win11-style titlebar (32px, drag-region, app-icon, _ ▢ ✕).
//
// The native chrome was disabled in tauri.conf.json (decorations: false)
// so we paint our own. Keeps the design tokens (radius, shadow) honest
// — Tauri's default titlebar would have flat 90° corners and clash.

import { Minus, Square, X, Zap } from "lucide-react";
import { useEffect, useState } from "react";

export function Titlebar() {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      const { getCurrentWindow } = await import("@tauri-apps/api/window");
      const w = getCurrentWindow();
      try {
        setMaximized(await w.isMaximized());
      } catch {
        /* ignore */
      }
      unlisten = await w.onResized(async () => {
        try {
          setMaximized(await w.isMaximized());
        } catch {
          /* ignore */
        }
      });
    })();
    return () => {
      if (unlisten) unlisten();
    };
  }, []);

  const minimize = async () => {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().minimize();
  };
  const toggleMax = async () => {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().toggleMaximize();
  };
  const close = async () => {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().close();
  };

  return (
    <div
      style={{
        flexShrink: 0,
        height: 32,
        display: "flex",
        alignItems: "center",
        background: "var(--bt-white)",
        borderBottom: "1px solid var(--bt-line)",
        userSelect: "none",
      }}
    >
      {/* Drag region — fills horizontal space between icon/title and window controls. */}
      <div
        data-tauri-drag-region
        style={{
          flex: 1,
          height: "100%",
          display: "flex",
          alignItems: "center",
          paddingLeft: 10,
          gap: 8,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 16,
            height: 16,
            borderRadius: 3,
            background: "var(--bt-ink)",
            color: "var(--bt-white)",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
          }}
        >
          <Zap size={10} strokeWidth={2.4} fill="currentColor" />
        </span>
        <span
          style={{
            fontFamily: "var(--font-app)",
            fontSize: "var(--fs-sm)",
            color: "var(--bt-muted)",
            pointerEvents: "none",
          }}
        >
          Blitztext
        </span>
      </div>

      <div style={{ display: "flex", height: "100%" }}>
        <CtrlButton onClick={minimize} aria-label="Minimieren">
          <Minus size={10} strokeWidth={1.8} />
        </CtrlButton>
        <CtrlButton onClick={toggleMax} aria-label={maximized ? "Wiederherstellen" : "Maximieren"}>
          <Square size={9} strokeWidth={1.8} />
        </CtrlButton>
        <CtrlButton onClick={close} aria-label="Schließen" hoverBg="#e81123" hoverInk="#fff">
          <X size={11} strokeWidth={1.8} />
        </CtrlButton>
      </div>
    </div>
  );
}

function CtrlButton({
  onClick,
  children,
  hoverBg = "var(--bt-paper-2)",
  hoverInk = "var(--bt-ink)",
  ...rest
}: {
  onClick: () => void;
  children: React.ReactNode;
  hoverBg?: string;
  hoverInk?: string;
} & React.HTMLAttributes<HTMLButtonElement>) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: 46,
        height: 32,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        background: hover ? hoverBg : "transparent",
        color: hover ? hoverInk : "var(--bt-muted-2)",
        border: 0,
        cursor: "default",
        transition: "background 80ms linear",
      }}
      {...rest}
    >
      {children}
    </button>
  );
}
