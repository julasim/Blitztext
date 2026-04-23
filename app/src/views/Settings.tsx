// Minimal settings view — Phase 1 just surfaces the environment state
// (CUDA, Ollama, paths). Real settings (model pick, HF token, shortcuts)
// land later.

import { Check, X as XIcon } from "lucide-react";
import { useMeetingStore } from "../state/useMeetingStore";

export function Settings() {
  const cfg = useMeetingStore((s) => s.config);
  const err = useMeetingStore((s) => s.configError);

  return (
    <div
      style={{
        flex: 1,
        padding: "32px 40px",
        overflowY: "auto",
        background: "var(--bt-white)",
      }}
    >
      <div style={{ maxWidth: 640 }}>
        <h2 style={{ fontSize: "var(--fs-xl)", fontWeight: 600, marginBottom: 16 }}>
          Einstellungen
        </h2>
        {err && (
          <div
            style={{
              padding: 12,
              border: "1px solid var(--bt-red)",
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-red-bg)",
              color: "var(--bt-red-ink)",
              fontSize: "var(--fs-sm)",
              marginBottom: 20,
            }}
          >
            Config konnte nicht geladen werden: {err}
          </div>
        )}

        <Card title="Umgebung">
          <BoolRow label="CUDA / GPU" ok={cfg?.cuda_available ?? false} />
          <BoolRow label="Ollama (lokal)" ok={cfg?.ollama_available ?? false} />
        </Card>

        <Card title="Pfade">
          <TextRow label="AppData" value={cfg?.appdata || "—"} mono />
          <TextRow label="Meetings" value={cfg?.meetings_dir || "—"} mono />
          <TextRow label="Modelle" value={cfg?.models_dir || "—"} mono />
          <TextRow label="Datenbank" value={cfg?.db_path || "—"} mono />
        </Card>

        <Card title="Whisper-Modelle">
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
              padding: "8px 0",
            }}
          >
            {(cfg?.whisper_models ?? []).map((m) => (
              <span
                key={m}
                style={{
                  padding: "4px 10px",
                  borderRadius: "var(--radius-sm)",
                  background: "var(--bt-stone)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--fs-xs)",
                }}
              >
                {m}
              </span>
            ))}
          </div>
        </Card>

        <p
          style={{
            marginTop: 24,
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            lineHeight: 1.6,
          }}
        >
          Weitere Einstellungen (Modellwahl, LLM-Prompt, Shortcuts, HF-Token)
          folgen in Phase 1-Ende / Phase 2.
        </p>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      style={{
        marginBottom: 16,
        border: "1px solid var(--bt-line)",
        borderRadius: "var(--radius-xl)",
        background: "var(--bt-white)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "10px 16px",
          borderBottom: "1px solid var(--bt-line-soft)",
          background: "var(--bt-paper-2)",
          fontSize: "var(--fs-sm)",
          fontWeight: 600,
          color: "var(--bt-muted)",
        }}
      >
        {title}
      </div>
      <div style={{ padding: "8px 16px" }}>{children}</div>
    </div>
  );
}

function BoolRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "10px 0",
        borderBottom: "1px solid var(--bt-line-soft)",
        fontSize: "var(--fs-sm)",
      }}
    >
      <span>{label}</span>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          color: ok ? "var(--bt-green)" : "var(--bt-red)",
        }}
      >
        {ok ? <Check size={14} /> : <XIcon size={14} />}
        {ok ? "verfügbar" : "nicht erreichbar"}
      </span>
    </div>
  );
}

function TextRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        padding: "10px 0",
        borderBottom: "1px solid var(--bt-line-soft)",
        fontSize: "var(--fs-sm)",
        gap: 2,
      }}
    >
      <span style={{ color: "var(--bt-muted-2)" }}>{label}</span>
      <span
        style={{
          color: "var(--bt-ink-soft)",
          fontFamily: mono ? "var(--font-mono)" : "inherit",
          fontSize: mono ? "var(--fs-xs)" : "inherit",
          wordBreak: "break-all",
        }}
      >
        {value}
      </span>
    </div>
  );
}
