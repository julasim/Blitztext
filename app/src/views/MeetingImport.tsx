// Drag & drop zone + file-picker fallback.
// The RPC `meeting.import_file` is still a stub pending the pyannote +
// whisper pipeline, so we keep the UI functional but surface a friendly
// "not yet wired" state on submission.

import { Upload, FileAudio, X } from "lucide-react";
import { useState } from "react";
import { call } from "../lib/rpc";
import { useMeetingStore } from "../state/useMeetingStore";

const ACCEPTED = [".wav", ".mp3", ".m4a", ".flac", ".ogg", ".mp4"];

export function MeetingImport() {
  const goLibrary = useMeetingStore((s) => s.goLibrary);
  const goReview = useMeetingStore((s) => s.goReview);
  const loadMeetings = useMeetingStore((s) => s.loadMeetings);
  const [hover, setHover] = useState(false);
  const [path, setPath] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const pick = async () => {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      multiple: false,
      filters: [
        {
          name: "Audio",
          extensions: ACCEPTED.map((e) => e.slice(1)),
        },
      ],
    });
    if (typeof selected === "string") {
      setPath(selected);
      if (!title) {
        const base = selected.split(/[\\/]/).pop() || "";
        setTitle(base.replace(/\.[^.]+$/, ""));
      }
    }
  };

  const submit = async () => {
    if (!path) return;
    setState("submitting");
    setError(null);
    try {
      const res = await call<{ meeting_id: string }>("meeting.import_file", {
        path,
        title: title || undefined,
      });
      await loadMeetings();
      goReview(res.meeting_id);
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: 48,
        gap: 20,
        background: "var(--bt-white)",
      }}
    >
      <div style={{ width: "100%", maxWidth: 640 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 20,
          }}
        >
          <h2 style={{ fontSize: "var(--fs-xl)", fontWeight: 600 }}>
            Meeting importieren
          </h2>
          <button
            type="button"
            onClick={goLibrary}
            style={{ color: "var(--bt-muted-2)", padding: 4 }}
            aria-label="Abbrechen"
          >
            <X size={18} />
          </button>
        </div>

        <Dropzone
          hover={hover}
          setHover={setHover}
          path={path}
          onClear={() => setPath(null)}
          onPick={pick}
          onFile={(p) => {
            setPath(p);
            if (!title) {
              const base = p.split(/[\\/]/).pop() || "";
              setTitle(base.replace(/\.[^.]+$/, ""));
            }
          }}
        />

        {path && (
          <div style={{ marginTop: 20 }}>
            <label
              style={{
                display: "block",
                fontSize: "var(--fs-xs)",
                textTransform: "uppercase",
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: "var(--bt-muted-2)",
                marginBottom: 6,
              }}
            >
              Titel
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Kurzer Meeting-Titel"
              style={{
                width: "100%",
                padding: "10px 12px",
                border: "1px solid var(--bt-line)",
                borderRadius: "var(--radius-lg)",
                fontSize: "var(--fs-base)",
              }}
            />
          </div>
        )}

        {error && (
          <div
            style={{
              marginTop: 16,
              padding: "12px 14px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-red)",
              background: "var(--bt-red-bg)",
              color: "var(--bt-red-ink)",
              fontSize: "var(--fs-sm)",
              fontFamily: "var(--font-mono)",
              lineHeight: 1.5,
            }}
          >
            {error}
          </div>
        )}

        <div
          style={{
            marginTop: 20,
            display: "flex",
            gap: 10,
            justifyContent: "flex-end",
          }}
        >
          <button
            type="button"
            onClick={goLibrary}
            style={{
              padding: "10px 16px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-line)",
              background: "var(--bt-white)",
              color: "var(--bt-muted)",
            }}
          >
            Abbrechen
          </button>
          <button
            type="button"
            disabled={!path || state === "submitting"}
            onClick={submit}
            style={{
              padding: "10px 20px",
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-ink)",
              color: "var(--bt-white)",
              fontWeight: 500,
              opacity: !path || state === "submitting" ? 0.5 : 1,
            }}
          >
            {state === "submitting" ? "Starte…" : "Transkribieren"}
          </button>
        </div>

        <p
          style={{
            marginTop: 24,
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            lineHeight: 1.6,
          }}
        >
          Die Transkription läuft lokal. Je nach Meeting-Länge und GPU
          dauert der Vorgang 1–10 Minuten. Fortschritt erscheint dann
          automatisch im Review-Bereich.
        </p>
      </div>
    </div>
  );
}

function Dropzone({
  hover,
  setHover,
  path,
  onClear,
  onPick,
  onFile,
}: {
  hover: boolean;
  setHover: (v: boolean) => void;
  path: string | null;
  onClear: () => void;
  onPick: () => void;
  onFile: (p: string) => void;
}) {
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setHover(true);
      }}
      onDragLeave={() => setHover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setHover(false);
        // In Tauri drag-drop events for files come via the window-level
        // `tauri://drag-drop` event, but a browser-side path is not
        // always exposed. For MVP we simply prompt the user to use the
        // picker when a drop can't be resolved.
        const first = e.dataTransfer.files[0];
        if (first && "path" in first && (first as any).path) {
          onFile((first as any).path);
        }
      }}
      style={{
        padding: 40,
        borderRadius: "var(--radius-2xl)",
        border: `2px dashed ${hover ? "var(--bt-ink)" : "var(--bt-line)"}`,
        background: hover ? "var(--bt-paper-2)" : "var(--bt-paper)",
        textAlign: "center",
        transition: "all 150ms ease",
      }}
    >
      {path ? (
        <div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 14px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-line)",
              background: "var(--bt-white)",
              fontFamily: "var(--font-mono)",
              fontSize: "var(--fs-sm)",
            }}
          >
            <FileAudio size={14} />
            <span
              style={{
                maxWidth: 380,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
              title={path}
            >
              {path}
            </span>
            <button
              type="button"
              onClick={onClear}
              style={{
                marginLeft: 4,
                color: "var(--bt-muted-2)",
                padding: 2,
              }}
              aria-label="Datei entfernen"
            >
              <X size={12} />
            </button>
          </div>
        </div>
      ) : (
        <div
          style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}
        >
          <div
            aria-hidden
            style={{
              width: 56,
              height: 56,
              borderRadius: "var(--radius-xl)",
              background: "var(--bt-white)",
              border: "1px solid var(--bt-line)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--bt-muted-2)",
            }}
          >
            <Upload size={22} strokeWidth={1.5} />
          </div>
          <div
            style={{
              fontSize: "var(--fs-md)",
              fontWeight: 500,
              color: "var(--bt-ink-soft)",
            }}
          >
            Audio-Datei hier ablegen
          </div>
          <div
            style={{
              fontSize: "var(--fs-sm)",
              color: "var(--bt-muted-2)",
            }}
          >
            oder
          </div>
          <button
            type="button"
            onClick={onPick}
            style={{
              padding: "8px 16px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-line)",
              background: "var(--bt-white)",
              fontSize: "var(--fs-sm)",
            }}
          >
            Datei auswählen…
          </button>
          <div
            style={{
              marginTop: 4,
              fontSize: "var(--fs-xs)",
              color: "var(--bt-subtle)",
              fontFamily: "var(--font-mono)",
            }}
          >
            {ACCEPTED.join(" · ")}
          </div>
        </div>
      )}
    </div>
  );
}
