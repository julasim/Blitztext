// Drop-Zone + Dateidialog für den Stapel-Import.
//
// Mehrere Dateien und ganze Ordner sind erlaubt; aufgelöst wird serverseitig
// (`queue.enqueue` → `audio_io.expand_paths`), weil das Frontend seit dem
// Entfernen des fs-Plugins bewusst nicht ins Dateisystem schaut. Die
// akzeptierten Endungen kommen aus `config.get`, damit es nur eine Liste gibt.
//
// Der Import selbst läuft über die Warteschlange: ein Job nach dem anderen,
// Fortschritt in der Seitenleiste.

import { FileAudio, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  useMeetingStore,
  type ModelChoice,
  type SkippedPath,
} from "../state/useMeetingStore";

const FALLBACK_EXTENSIONS = [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4"];

/** "" = Automatik (Sidecar wählt: large-v3 mit GPU, sonst medium). */
const MODEL_AUTO = "";

/** Muss zu `core/parakeet.MODEL_ID` passen — kommt über `config.models`. */
const PARAKEET_ID = "parakeet-tdt-0.6b-v3";

export function MeetingImport() {
  const goLibrary = useMeetingStore((s) => s.goLibrary);
  const enqueue = useMeetingStore((s) => s.enqueue);
  const config = useMeetingStore((s) => s.config);

  const [hover, setHover] = useState(false);
  const [paths, setPaths] = useState<string[]>([]);
  const [model, setModel] = useState<string>(MODEL_AUTO);
  const [vocabulary, setVocabulary] = useState("");
  /** Bekannte Teilnehmerzahl. Leer = pyannote schätzt selbst.
   *
   *  Die Parameter gehen seit jeher durch die ganze Kette bis in die
   *  Pipeline — nur einstellen konnte man sie nirgends. Bei bekannter
   *  Rundengröße muss die Sprechertrennung nicht in jedem Abschnitt neu
   *  raten, was gerade bei Tischmikrofonen den Unterschied macht. */
  const [speakers, setSpeakers] = useState("");
  // Nur zwei Zustände: der frühere Wert "error" wurde gesetzt, aber
  // nirgends gelesen — angezeigt wird der Fehler über `error`.
  const [state, setState] = useState<"idle" | "submitting">("idle");
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<SkippedPath[]>([]);
  /** Begriffe, die der Sidecar an der Token-Grenze aus dem Vokabular
   *  geworfen hat. Das Backend meldet sie ausdrücklich zurück — „ein still
   *  gekürztes Vokabular ist ein Fehler, den niemand bemerkt". */
  const [dropped, setDropped] = useState<string[]>([]);

  const extensions = useMemo(
    () => config?.audio_extensions ?? FALLBACK_EXTENSIONS,
    [config],
  );

  /** Parakeets TDT-Decoder kennt kein Vokabular-Priming. Eine Stelle für
   *  Anzeige **und** Absenden — vorher war das Feld zwar ausgegraut, der
   *  Wert ging aber trotzdem mit. */
  const vokabularAus = model === PARAKEET_ID;

  const addPaths = (incoming: string[]) => {
    setSkipped([]);
    setDropped([]);
    // Auch die Fehlermeldung: sie bezog sich auf den vorigen Versuch und
    // blieb sonst über der frischen Auswahl stehen.
    setError(null);
    setState("idle");
    setPaths((current) => {
      const merged = new Set(current);
      for (const p of incoming) merged.add(p);
      return [...merged];
    });
  };

  // Tauri 2 gibt Dateipfade nicht über die HTML5-dataTransfer-API heraus
  // (Sandbox), deshalb der native Fenster-Event. Ordner kommen hier als
  // ganz normaler Pfad an — auflösen tut sie der Sidecar.
  useEffect(() => {
    let unlisten: (() => void) | undefined;
    (async () => {
      try {
        const { getCurrentWebview } = await import("@tauri-apps/api/webview");
        unlisten = await getCurrentWebview().onDragDropEvent((evt) => {
          if (evt.payload.type === "enter" || evt.payload.type === "over") {
            setHover(true);
          } else if (evt.payload.type === "leave") {
            setHover(false);
          } else if (evt.payload.type === "drop") {
            setHover(false);
            addPaths(evt.payload.paths);
          }
        });
      } catch (e) {
        console.warn("drag-drop wiring failed:", e);
      }
    })();
    return () => {
      if (unlisten) unlisten();
    };
  }, []);

  const pick = async () => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        multiple: true,
        filters: [
          { name: "Audio", extensions: extensions.map((e) => e.replace(/^\./, "")) },
        ],
      });
      if (Array.isArray(selected)) addPaths(selected);
      else if (typeof selected === "string") addPaths([selected]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const pickFolder = async () => {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({ directory: true, multiple: false });
      if (typeof selected === "string") addPaths([selected]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submit = async () => {
    if (paths.length === 0) return;
    setState("submitting");
    setError(null);
    try {
      const anzahl = Number.parseInt(speakers, 10);
      const res = await enqueue(paths, {
        ...(model === MODEL_AUTO ? {} : { whisper_model: model }),
        // Bekannte Zahl heißt: genau so viele, nicht "höchstens".
        ...(Number.isFinite(anzahl) && anzahl >= 1
          ? { min_speakers: anzahl, max_speakers: anzahl }
          : {}),
        // Bei Parakeet ist das Feld deaktiviert — dann darf der Wert auch
        // nicht mitgehen. Sonst meldet der Sidecar womöglich gekürzte
        // Begriffe zurück für ein Vokabular, das ohnehin nie gewirkt hätte.
        ...(vocabulary.trim() && !vokabularAus
          ? { vocabulary: vocabulary.trim() }
          : {}),
      });
      if (res.count === 0) {
        setState("idle");
        setSkipped(res.skipped);
        setError("Nichts eingereiht — keine verwertbare Audiodatei dabei.");
        return;
      }
      setSkipped(res.skipped);
      setDropped(res.vocabulary_dropped ?? []);
      setPaths([]);
      setState("idle");
      // Nur weiterspringen, wenn es nichts zu berichten gibt. Vorher stand
      // hier immer `goLibrary()` — die Ansicht wurde abgebaut, bevor die
      // Liste der übersprungenen Dateien je gerendert war. Wer 50 Dateien
      // einwarf, von denen 10 nicht unterstützt sind, erfuhr davon nichts
      // und vermisste sie später kommentarlos.
      if (res.skipped.length === 0 && (res.vocabulary_dropped ?? []).length === 0) {
        goLibrary();
      }
    } catch (e) {
      setState("idle");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div
      style={{
        flex: 1,
        minHeight: 0, // sonst greift overflowY nicht (Flex-Standard: min-height: auto)
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: 48,
        gap: 20,
        overflowY: "auto",
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
            Dateien transkribieren
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
          count={paths.length}
          extensions={extensions}
          onPick={pick}
          onPickFolder={pickFolder}
        />

        {paths.length > 0 && (
          <PathList paths={paths} onRemove={(p) => setPaths((c) => c.filter((x) => x !== p))} />
        )}

        {paths.length > 0 && (
          <ModelPicker
            models={config?.models ?? []}
            value={model}
            onChange={setModel}
          />
        )}

        {paths.length > 0 && (
          <SpeakerCountField value={speakers} onChange={setSpeakers} />
        )}

        {paths.length > 0 && (
          <VocabularyField
            value={vocabulary}
            onChange={setVocabulary}
            disabled={vokabularAus}
          />
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

        {skipped.length > 0 && <SkippedList skipped={skipped} />}

        {dropped.length > 0 && (
          <div
            style={{
              marginTop: 14,
              padding: "10px 12px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-line)",
              background: "var(--bt-paper)",
              fontSize: "var(--fs-sm)",
              lineHeight: 1.5,
            }}
          >
            <strong>Vokabular gekürzt.</strong> Whisper nimmt nur eine
            begrenzte Anzahl Begriffe entgegen. Nicht übernommen wurden:{" "}
            <span style={{ fontFamily: "var(--font-mono)" }}>
              {dropped.join(", ")}
            </span>
          </div>
        )}

        {(skipped.length > 0 || dropped.length > 0) && paths.length === 0 && (
          <button
            type="button"
            onClick={() => {
              setSkipped([]);
              setDropped([]);
              goLibrary();
            }}
            style={{
              marginTop: 14,
              padding: "8px 14px",
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-ink)",
              color: "var(--bt-white)",
              fontSize: "var(--fs-sm)",
              fontWeight: 500,
            }}
          >
            Weiter zur Bibliothek
          </button>
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
            disabled={paths.length === 0 || state === "submitting"}
            onClick={submit}
            style={{
              padding: "10px 20px",
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-ink)",
              color: "var(--bt-white)",
              fontWeight: 500,
              opacity: paths.length === 0 || state === "submitting" ? 0.5 : 1,
            }}
          >
            {state === "submitting"
              ? "Reihe ein…"
              : paths.length > 1
                ? `${paths.length} Einträge einreihen`
                : "Transkribieren"}
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
          Die Transkription läuft lokal und nacheinander — eine Datei nach der
          anderen, damit sich zwei Läufe nicht die Grafikkarte streitig machen.
          Der Fortschritt steht in der Seitenleiste, abbrechen geht dort auch.
        </p>
      </div>
    </div>
  );
}

/** Bekannte Teilnehmerzahl.
 *
 * Ohne Vorgabe schätzt pyannote die Sprecherzahl selbst — und muss dabei
 * in jedem Abschnitt neu entscheiden. Bei einem Mikrofon in der Tischmitte,
 * wo die Entfernten leise und ähnlich klingen, führt das zu ständig
 * überlappenden Segmenten und damit zu zerhackten Absätzen. Eine bekannte
 * Zahl nimmt der Trennung diese Freiheit.
 */
function SpeakerCountField({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <label
        htmlFor="sprecherzahl"
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
        Anzahl Sprecher
      </label>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <input
          id="sprecherzahl"
          type="number"
          min={1}
          max={20}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="automatisch"
          style={{
            width: 120,
            padding: "8px 10px",
            borderRadius: "var(--radius-lg)",
            border: "1px solid var(--bt-line)",
            background: "var(--bt-white)",
            fontSize: "var(--fs-sm)",
          }}
        />
        <span
          style={{
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            lineHeight: 1.5,
          }}
        >
          Leer lassen, wenn unbekannt. Eine richtige Angabe verbessert die
          Sprechertrennung deutlich — besonders bei Aufnahmen mit einem
          Mikrofon in der Tischmitte.
        </span>
      </div>
    </div>
  );
}

function VocabularyField({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
}) {
  return (
    <div style={{ marginTop: 16, opacity: disabled ? 0.55 : 1 }}>
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
        Vokabular für diese Aufnahme
      </label>
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Teilnehmernamen, Projektkürzel, Fachbegriffe — durch Komma getrennt"
        style={{
          width: "100%",
          padding: "10px 12px",
          border: "1px solid var(--bt-line)",
          borderRadius: "var(--radius-lg)",
          fontSize: "var(--fs-base)",
          background: disabled ? "var(--bt-paper)" : "var(--bt-white)",
        }}
      />
      <p
        style={{
          marginTop: 6,
          fontSize: "var(--fs-xs)",
          color: "var(--bt-subtle)",
          lineHeight: 1.5,
        }}
      >
        {disabled
          ? "Parakeet unterstützt kein Vokabular — für Namen und Fachbegriffe ein Whisper-Modell wählen."
          : "Wird mit der Wortliste aus den Einstellungen zusammengeführt. Wenige, treffende Begriffe wirken besser als lange Listen."}
      </p>
    </div>
  );
}

function ModelPicker({
  models,
  value,
  onChange,
}: {
  models: ModelChoice[];
  value: string;
  onChange: (v: string) => void;
}) {
  const active = models.find((m) => m.id === value);
  return (
    <div style={{ marginTop: 16 }}>
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
        Modell
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%",
          padding: "10px 12px",
          border: "1px solid var(--bt-line)",
          borderRadius: "var(--radius-lg)",
          fontSize: "var(--fs-base)",
          background: "var(--bt-white)",
        }}
      >
        <option value="">Automatisch</option>
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
      <p
        style={{
          marginTop: 6,
          fontSize: "var(--fs-xs)",
          color: "var(--bt-subtle)",
          lineHeight: 1.5,
        }}
      >
        {active
          ? active.hint
          : "Wählt selbst: höchste Genauigkeit mit GPU, sonst ein ausgewogenes Modell."}
      </p>
    </div>
  );
}

function Dropzone({
  hover,
  count,
  extensions,
  onPick,
  onPickFolder,
}: {
  hover: boolean;
  count: number;
  extensions: string[];
  onPick: () => void;
  onPickFolder: () => void;
}) {
  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      style={{
        padding: 40,
        borderRadius: "var(--radius-2xl)",
        border: `2px dashed ${hover ? "var(--bt-ink)" : "var(--bt-line)"}`,
        background: hover ? "var(--bt-paper-2)" : "var(--bt-paper)",
        textAlign: "center",
        transition: "all 150ms ease",
      }}
    >
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
          {count > 0
            ? "Weitere Dateien oder Ordner ablegen"
            : "Dateien oder ganze Ordner hier ablegen"}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
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
            Dateien wählen…
          </button>
          <button
            type="button"
            onClick={onPickFolder}
            style={{
              padding: "8px 16px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-line)",
              background: "var(--bt-white)",
              fontSize: "var(--fs-sm)",
            }}
          >
            Ordner wählen…
          </button>
        </div>
        <div
          style={{
            marginTop: 4,
            fontSize: "var(--fs-xs)",
            color: "var(--bt-subtle)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {extensions.slice(0, 6).join(" · ")}
        </div>
      </div>
    </div>
  );
}

function PathList({
  paths,
  onRemove,
}: {
  paths: string[];
  onRemove: (path: string) => void;
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <div
        style={{
          fontSize: "var(--fs-xs)",
          textTransform: "uppercase",
          fontWeight: 600,
          letterSpacing: "0.08em",
          color: "var(--bt-muted-2)",
          marginBottom: 8,
        }}
      >
        {paths.length} {paths.length === 1 ? "Eintrag" : "Einträge"}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 220, overflowY: "auto" }}>
        {paths.map((p) => (
          <div
            key={p}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 12px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--bt-line)",
              background: "var(--bt-white)",
              fontFamily: "var(--font-mono)",
              fontSize: "var(--fs-sm)",
            }}
          >
            <FileAudio size={14} style={{ flexShrink: 0 }} />
            <span
              style={{
                flex: 1,
                minWidth: 0,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                direction: "rtl",
                textAlign: "left",
              }}
              title={p}
            >
              {p}
            </span>
            <button
              type="button"
              onClick={() => onRemove(p)}
              style={{ color: "var(--bt-muted-2)", padding: 2, flexShrink: 0 }}
              aria-label="Entfernen"
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function SkippedList({ skipped }: { skipped: SkippedPath[] }) {
  return (
    <div
      style={{
        marginTop: 16,
        padding: "12px 14px",
        borderRadius: "var(--radius-lg)",
        border: "1px solid var(--bt-line)",
        background: "var(--bt-paper)",
        fontSize: "var(--fs-sm)",
        lineHeight: 1.6,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>
        {skipped.length} übersprungen
      </div>
      {skipped.slice(0, 8).map((s) => (
        <div key={s.path + s.reason} style={{ color: "var(--bt-muted)" }}>
          <span style={{ fontFamily: "var(--font-mono)" }}>
            {s.path.split(/[\\/]/).pop()}
          </span>{" "}
          — {s.reason}
        </div>
      ))}
      {skipped.length > 8 && (
        <div style={{ color: "var(--bt-subtle)", marginTop: 4 }}>
          … und {skipped.length - 8} weitere
        </div>
      )}
    </div>
  );
}
