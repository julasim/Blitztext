// Settings — environment status + editable secrets (HF token).
//
// Phase-1 keeps it minimal: surface what we have, let the user fix the
// HF token without leaving the app. Whisper/Ollama model dropdowns and
// other prefs land in Phase 2 alongside the dictation migration.

import { Check, Eye, EyeOff, Loader2, X as XIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { call } from "../lib/rpc";
import { useMeetingStore } from "../state/useMeetingStore";

type SettingsSnapshot = {
  hf_token_present: boolean;
  hf_token_hint: string;
  whisper_default: string;
  ollama_default: string;
};

type TokenStatus = {
  ok: boolean;
  stage: "missing" | "auth" | "gated" | "ready" | "deps";
  user?: string;
  message: string;
};

export function Settings() {
  const cfg = useMeetingStore((s) => s.config);
  const cfgErr = useMeetingStore((s) => s.configError);

  return (
    <div
      style={{
        flex: 1,
        padding: "32px 40px",
        overflowY: "auto",
        background: "var(--bt-white)",
      }}
    >
      <div style={{ maxWidth: 720 }}>
        <h2
          style={{
            fontSize: "var(--fs-xl)",
            fontWeight: 600,
            marginBottom: 16,
          }}
        >
          Einstellungen
        </h2>
        {cfgErr && (
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
            Config konnte nicht geladen werden: {cfgErr}
          </div>
        )}

        <Card title="Umgebung">
          <BoolRow label="CUDA / GPU" ok={cfg?.cuda_available ?? false} />
          <BoolRow
            label="Ollama (lokal)"
            ok={cfg?.ollama_available ?? false}
          />
        </Card>

        <Card title="HuggingFace">
          <p
            style={{
              fontSize: "var(--fs-sm)",
              color: "var(--bt-muted)",
              lineHeight: 1.6,
              marginBottom: 14,
            }}
          >
            Wird für die Sprecher-Erkennung (pyannote-Modelle) gebraucht. Token
            mit „Read"-Recht und aktivierter Berechtigung „
            <em>Read access to contents of all public gated repos you can access</em>".
            Lizenzen für{" "}
            <code>pyannote/speaker-diarization-3.1</code> und{" "}
            <code>pyannote/segmentation-3.0</code> auf huggingface.co müssen
            akzeptiert sein.
          </p>
          <HfTokenEditor />
        </Card>

        <Card title="Modelle (Defaults)">
          <TextRow
            label="Whisper"
            value={cfg?.whisper_models?.[5] ?? "large-v3-turbo"}
            mono
          />
          <TextRow label="Ollama Cleanup" value="qwen2.5:7b-instruct" mono />
          <p
            style={{
              fontSize: "var(--fs-xs)",
              color: "var(--bt-subtle)",
              marginTop: 10,
              lineHeight: 1.5,
            }}
          >
            Modell-Auswahl pro Aufnahme (klein/groß für Geschwindigkeit vs.
            Qualität) folgt mit der Dictate-Migration.
          </p>
        </Card>

        <Card title="Pfade">
          <TextRow label="AppData" value={cfg?.appdata || "—"} mono />
          <TextRow label="Meetings" value={cfg?.meetings_dir || "—"} mono />
          <TextRow label="Modelle" value={cfg?.models_dir || "—"} mono />
          <TextRow label="Datenbank" value={cfg?.db_path || "—"} mono />
        </Card>

        <p
          style={{
            marginTop: 24,
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            lineHeight: 1.6,
          }}
        >
          Weitere Einstellungen (Diktier-Modus-Hotkeys, LLM-Provider-Keys,
          Sprache) folgen mit der Dictate-Migration.
        </p>
      </div>
    </div>
  );
}

function HfTokenEditor() {
  const [snap, setSnap] = useState<SettingsSnapshot | null>(null);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [status, setStatus] = useState<TokenStatus | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const s = await call<SettingsSnapshot>("settings.get");
      setSnap(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // Beim Mount einmal laden. Bewusst inline statt `refresh()`: der
  // cancelled-Guard verhindert setState nach dem Unmount.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const s = await call<SettingsSnapshot>("settings.get");
        if (!cancelled) setSnap(s);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const probe = async () => {
    setStatusBusy(true);
    setError(null);
    try {
      const r = await call<TokenStatus>("settings.test_hf_token");
      setStatus(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStatusBusy(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await call("settings.set_hf_token", { token: value });
      setValue("");
      setEditing(false);
      await refresh();
      // Auto-probe so the user immediately sees green/yellow/red.
      await probe();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm("Gespeicherten HF-Token wirklich löschen?")) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      await call("settings.set_hf_token", { token: "" });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (!snap) {
    return (
      <div style={{ color: "var(--bt-subtle)", fontSize: "var(--fs-sm)" }}>
        Lade…
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {!editing && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 12px",
            border: "1px solid var(--bt-line)",
            borderRadius: "var(--radius-lg)",
            background: snap.hf_token_present
              ? "var(--bt-paper-2)"
              : "var(--bt-paper)",
            fontFamily: "var(--font-mono)",
            fontSize: "var(--fs-sm)",
          }}
        >
          <span style={{ flex: 1, color: "var(--bt-ink-soft)" }}>
            {snap.hf_token_present ? snap.hf_token_hint : "kein Token gespeichert"}
          </span>
          <button
            type="button"
            onClick={() => {
              setEditing(true);
              setValue("");
              setReveal(false);
            }}
            style={btnGhost()}
          >
            {snap.hf_token_present ? "Ändern" : "Setzen"}
          </button>
          {snap.hf_token_present && (
            <button
              type="button"
              onClick={remove}
              disabled={saving}
              style={btnGhost("var(--bt-red-ink)")}
            >
              Löschen
            </button>
          )}
        </div>
      )}

      {editing && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: 12,
            border: "1px solid var(--bt-line)",
            borderRadius: "var(--radius-lg)",
            background: "var(--bt-paper)",
          }}
        >
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type={reveal ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="hf_..."
              autoFocus
              spellCheck={false}
              autoComplete="off"
              style={{
                flex: 1,
                padding: "8px 10px",
                border: "1px solid var(--bt-line)",
                borderRadius: "var(--radius-sm)",
                background: "var(--bt-white)",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--fs-sm)",
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && value.trim()) void save();
                if (e.key === "Escape") {
                  setEditing(false);
                  setValue("");
                }
              }}
            />
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              style={btnGhost()}
              title={reveal ? "Verbergen" : "Anzeigen"}
            >
              {reveal ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setValue("");
              }}
              disabled={saving}
              style={btnGhost()}
            >
              Abbrechen
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving || !value.trim()}
              style={btnPrimary(saving || !value.trim())}
            >
              {saving ? "Speichere…" : "Speichern"}
            </button>
          </div>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button
          type="button"
          onClick={probe}
          disabled={statusBusy || !snap.hf_token_present}
          style={btnGhost()}
        >
          {statusBusy ? (
            <>
              <Loader2 size={12} className="bt-spin" /> Teste…
            </>
          ) : (
            "Token prüfen"
          )}
        </button>
        {status && <StatusPill s={status} />}
      </div>

      {error && (
        <div
          style={{
            padding: "8px 10px",
            borderRadius: "var(--radius-sm)",
            background: "var(--bt-red-bg)",
            color: "var(--bt-red-ink)",
            fontSize: "var(--fs-xs)",
            fontFamily: "var(--font-mono)",
            lineHeight: 1.5,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}

function StatusPill({ s }: { s: TokenStatus }) {
  const palette: Record<TokenStatus["stage"], { bg: string; ink: string; icon: React.ReactNode }> = {
    ready: { bg: "#d1fadf", ink: "#065f46", icon: <Check size={12} /> },
    gated: {
      bg: "#fef3c7",
      ink: "#92400e",
      icon: <span style={{ fontWeight: 700 }}>!</span>,
    },
    auth: { bg: "var(--bt-red-bg)", ink: "var(--bt-red-ink)", icon: <XIcon size={12} /> },
    missing: { bg: "var(--bt-stone)", ink: "var(--bt-muted)", icon: <span>—</span> },
    deps: { bg: "var(--bt-stone)", ink: "var(--bt-muted)", icon: <span>?</span> },
  };
  const p = palette[s.stage];
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 10px",
        borderRadius: "var(--radius-sm)",
        background: p.bg,
        color: p.ink,
        fontSize: "var(--fs-xs)",
        lineHeight: 1.5,
      }}
    >
      {p.icon}
      <span style={{ flex: 1 }}>{s.message}</span>
    </div>
  );
}

// --- Atoms ----------------------------------------------------------------

function btnGhost(color?: string): React.CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 12px",
    border: "1px solid var(--bt-line)",
    borderRadius: "var(--radius-sm)",
    background: "var(--bt-white)",
    color: color || "var(--bt-muted)",
    fontSize: "var(--fs-xs)",
  };
}

function btnPrimary(disabled = false): React.CSSProperties {
  return {
    padding: "6px 14px",
    borderRadius: "var(--radius-sm)",
    background: "var(--bt-ink)",
    color: "var(--bt-white)",
    fontSize: "var(--fs-xs)",
    opacity: disabled ? 0.5 : 1,
  };
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
      <div style={{ padding: "12px 16px" }}>{children}</div>
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
        padding: "8px 0",
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

function TextRow({
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
        flexDirection: "column",
        padding: "8px 0",
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
