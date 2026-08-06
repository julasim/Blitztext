// Sachprotokoll über dem Transkript.
//
// Verdichtet, was in eine Projektakte gehört: besprochene Sachverhalte,
// Hinweise, Entscheidungen, offene Punkte. Etwas anderes als der Cleanup,
// der nur Füllwörter aus den einzelnen Absätzen entfernt.
//
// Bewusst einklappbar und standardmäßig zu: Wer das Wortprotokoll lesen
// will, soll nicht erst daran vorbeiscrollen.

import { AlertTriangle, ChevronDown, ChevronRight, FileText, Loader2 } from "lucide-react";
import { useState } from "react";
import { useMeetingStore } from "../state/useMeetingStore";

export function ProtocolView() {
  const protocol = useMeetingStore((s) => s.protocol);
  const running = useMeetingStore((s) => s.protocolRunning);
  const fehler = useMeetingStore((s) => s.protocolError);
  const fortschritt = useMeetingStore((s) => s.protocolProgress);
  const runProtocol = useMeetingStore((s) => s.runProtocol);
  const ollamaDa = useMeetingStore((s) => s.config?.ollama_available ?? false);
  const [offen, setOffen] = useState(false);

  // Sobald ein Protokoll vorliegt, lohnt sich das Aufklappen — vorher zeigt
  // die Leiste nur den Knopf.
  const zeigeInhalt = offen && !!protocol;

  return (
    <div
      style={{
        flexShrink: 0,
        borderBottom: "1px solid var(--bt-line)",
        background: "var(--bt-paper)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 20px",
        }}
      >
        <button
          type="button"
          onClick={() => setOffen((v) => !v)}
          disabled={!protocol}
          title={protocol ? "Protokoll ein-/ausklappen" : "Noch kein Protokoll"}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            background: "transparent",
            border: "none",
            padding: 0,
            cursor: protocol ? "pointer" : "default",
            color: protocol ? "var(--bt-ink)" : "var(--bt-muted-2)",
            fontSize: "var(--fs-sm)",
            fontWeight: 600,
          }}
        >
          {protocol ? (
            zeigeInhalt ? <ChevronDown size={14} /> : <ChevronRight size={14} />
          ) : (
            <FileText size={14} />
          )}
          Protokoll
        </button>

        <span style={{ flex: 1, fontSize: "var(--fs-xs)", color: "var(--bt-subtle)" }}>
          {running
            ? fortschritt
              ? `Abschnitt ${fortschritt.done} von ${fortschritt.total} …`
              : "wird erstellt …"
            : protocol
              ? "Sachverhalt, Entscheidungen und offene Punkte"
              : "aus dem Transkript erzeugen"}
        </span>

        <button
          type="button"
          disabled={running || !ollamaDa}
          onClick={() => void runProtocol()}
          title={
            ollamaDa
              ? undefined
              : "Braucht ein laufendes Ollama (siehe Statusleiste)"
          }
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 12px",
            borderRadius: "var(--radius-lg)",
            background: "var(--bt-ink)",
            color: "var(--bt-white)",
            fontSize: "var(--fs-xs)",
            fontWeight: 500,
            opacity: running || !ollamaDa ? 0.5 : 1,
          }}
        >
          {running && <Loader2 size={12} className="bt-spin" />}
          {protocol ? "Neu erstellen" : "Protokoll erstellen"}
        </button>
      </div>

      {fehler && (
        <div
          role="alert"
          style={{
            padding: "8px 20px 10px",
            fontSize: "var(--fs-xs)",
            color: "var(--bt-red-ink)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {fehler}
        </div>
      )}

      {zeigeInhalt && (
        <div
          style={{
            maxHeight: "50vh",
            overflowY: "auto",
            padding: "4px 20px 16px",
            borderTop: "1px solid var(--bt-line)",
          }}
        >
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "flex-start",
              padding: "8px 10px",
              marginBottom: 12,
              borderRadius: "var(--radius-lg)",
              background: "var(--bt-paper-2)",
              fontSize: "var(--fs-xs)",
              color: "var(--bt-muted)",
              lineHeight: 1.5,
            }}
          >
            <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 2 }} aria-hidden />
            <span>
              Maschinell erzeugt. <strong>Zahlen, Maße und Fristen vor der
              Verwendung gegenlesen</strong> — sie stammen aus einem
              automatischen Transkript und werden nicht geprüft.
            </span>
          </div>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "var(--font-app)",
              fontSize: "var(--fs-sm)",
              lineHeight: 1.6,
              margin: 0,
            }}
          >
            {protocol}
          </pre>
        </div>
      )}
    </div>
  );
}
