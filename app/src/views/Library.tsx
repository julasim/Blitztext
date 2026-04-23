// Default view when nothing is selected. Shows an empty state + big CTA.

import { FileAudio, Upload } from "lucide-react";
import { useMeetingStore } from "../state/useMeetingStore";

export function Library() {
  const goImport = useMeetingStore((s) => s.goImport);
  const meetings = useMeetingStore((s) => s.meetings);
  const cfg = useMeetingStore((s) => s.config);

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 20,
        padding: 48,
        background: "var(--bt-white)",
      }}
    >
      <div
        aria-hidden
        style={{
          width: 72,
          height: 72,
          borderRadius: "var(--radius-2xl)",
          background: "var(--bt-paper)",
          border: "1px solid var(--bt-line)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--bt-muted-2)",
        }}
      >
        <FileAudio size={28} strokeWidth={1.4} />
      </div>
      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <h2 style={{ fontSize: "var(--fs-xl)", marginBottom: 8 }}>
          {meetings.length === 0 ? "Kein Meeting vorhanden" : "Wähle ein Meeting"}
        </h2>
        <p style={{ color: "var(--bt-muted)", lineHeight: 1.6 }}>
          {meetings.length === 0
            ? "Importiere eine Audio-Datei (WAV, MP3, M4A, FLAC, OGG). Blitztext transkribiert lokal, erkennt Sprecher automatisch und bereitet das Protokoll für dich vor."
            : "Öffne eine Aufnahme aus der Sidebar, oder starte einen neuen Import."}
        </p>
      </div>
      <button
        type="button"
        onClick={goImport}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "12px 20px",
          borderRadius: "var(--radius-lg)",
          background: "var(--bt-ink)",
          color: "var(--bt-white)",
          fontSize: "var(--fs-base)",
          fontWeight: 500,
        }}
      >
        <Upload size={16} />
        Audio importieren
      </button>
      {cfg && (
        <div
          style={{
            marginTop: 12,
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            fontFamily: "var(--font-mono)",
            display: "flex",
            gap: 12,
          }}
        >
          <span title="CUDA-Beschleunigung">
            GPU {cfg.cuda_available ? "✓" : "—"}
          </span>
          <span title="Ollama lokal erreichbar">
            Ollama {cfg.ollama_available ? "✓" : "—"}
          </span>
        </div>
      )}
    </div>
  );
}
