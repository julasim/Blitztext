// Warteschlange in der Seitenleiste.
//
// Zeigt nur, was gerade zählt: der laufende Job mit Stage und Fortschritt,
// die Wartenden darunter, und Fehlgeschlagenes mit Grund. Ist nichts
// eingereiht, verschwindet der ganze Block — kein leerer Rahmen.

import { AlertCircle, Loader2, X } from "lucide-react";
import { STAGE_LABEL } from "../lib/format";
import { useMeetingStore } from "../state/useMeetingStore";
import type { Job } from "../lib/types";

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

export function QueuePanel() {
  const jobs = useMeetingStore((s) => s.jobs);
  const progress = useMeetingStore((s) => s.progress);
  const cancelJob = useMeetingStore((s) => s.cancelJob);
  const clearFinishedJobs = useMeetingStore((s) => s.clearFinishedJobs);

  const running = jobs.filter((j) => j.state === "running");
  const queued = jobs.filter((j) => j.state === "queued");
  const failed = jobs.filter((j) => j.state === "failed");
  const finished = jobs.filter(
    (j) => j.state === "done" || j.state === "failed" || j.state === "cancelled",
  );

  // `finished` gehört in die Bedingung: der Aufräumen-Knopf hängt daran.
  // Ohne ihn verschwand der ganze Block, sobald nichts mehr lief — erledigte
  // Jobs sammelten sich in der DB und ließen sich nur noch löschen, solange
  // zufällig gerade ein anderer Import lief.
  if (
    running.length === 0 &&
    queued.length === 0 &&
    failed.length === 0 &&
    finished.length === 0
  ) {
    return null;
  }

  return (
    <div
      style={{
        padding: "8px 8px 10px",
        borderBottom: "1px solid var(--bt-line)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          padding: "2px 6px 4px",
        }}
      >
        <span
          style={{
            fontSize: "var(--fs-xs)",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: "var(--bt-subtle)",
          }}
        >
          Warteschlange
        </span>
        {finished.length > 0 && (
          <button
            type="button"
            onClick={() => void clearFinishedJobs()}
            style={{
              fontSize: "var(--fs-xs)",
              color: "var(--bt-muted-2)",
              padding: 2,
            }}
          >
            aufräumen
          </button>
        )}
      </div>

      {running.map((job) => (
        <RunningRow
          key={job.id}
          job={job}
          pct={job.meeting_id ? progress[job.meeting_id]?.pct : undefined}
          stage={job.meeting_id ? progress[job.meeting_id]?.stage : undefined}
          onCancel={() => void cancelJob(job.id)}
        />
      ))}

      {queued.map((job, i) => (
        <QueuedRow
          key={job.id}
          job={job}
          index={i + 1}
          onCancel={() => void cancelJob(job.id)}
        />
      ))}

      {failed.map((job) => (
        <FailedRow key={job.id} job={job} />
      ))}
    </div>
  );
}

function RunningRow({
  job,
  pct,
  stage,
  onCancel,
}: {
  job: Job;
  pct?: number;
  stage?: string;
  onCancel: () => void;
}) {
  const percent = Math.round((pct ?? 0) * 100);
  return (
    <div
      style={{
        padding: "8px 8px 9px",
        borderRadius: "var(--radius-lg)",
        background: "var(--bt-paper)",
        border: "1px solid var(--bt-line)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Loader2 size={12} className="bt-spin" style={{ flexShrink: 0 }} aria-hidden />
        <span
          style={{
            flex: 1,
            minWidth: 0,
            fontSize: "var(--fs-sm)",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={job.source_path}
        >
          {fileName(job.source_path)}
        </span>
        <button
          type="button"
          onClick={onCancel}
          title="Abbrechen"
          aria-label="Abbrechen"
          style={{ color: "var(--bt-muted-2)", padding: 2, flexShrink: 0 }}
        >
          <X size={12} />
        </button>
      </div>

      <div
        style={{
          height: 3,
          borderRadius: 2,
          background: "var(--bt-line)",
          margin: "7px 0 5px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: "100%",
            background: "var(--bt-ink)",
            transition: "width 200ms linear",
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "var(--fs-xs)",
          color: "var(--bt-subtle)",
          fontFamily: "var(--font-mono)",
        }}
      >
        <span>{stage ? STAGE_LABEL[stage] ?? stage : "Startet…"}</span>
        <span>{percent}%</span>
      </div>
    </div>
  );
}

function QueuedRow({
  job,
  index,
  onCancel,
}: {
  job: Job;
  index: number;
  onCancel: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 8px",
        fontSize: "var(--fs-sm)",
        color: "var(--bt-muted)",
      }}
    >
      <span
        style={{
          flexShrink: 0,
          width: 16,
          fontSize: "var(--fs-xs)",
          fontFamily: "var(--font-mono)",
          color: "var(--bt-subtle)",
        }}
      >
        {index}.
      </span>
      <span
        style={{
          flex: 1,
          minWidth: 0,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
        title={job.source_path}
      >
        {fileName(job.source_path)}
      </span>
      <button
        type="button"
        onClick={onCancel}
        title="Aus der Warteschlange nehmen"
        aria-label="Aus der Warteschlange nehmen"
        style={{ color: "var(--bt-muted-2)", padding: 2, flexShrink: 0 }}
      >
        <X size={12} />
      </button>
    </div>
  );
}

function FailedRow({ job }: { job: Job }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 6,
        padding: "6px 8px",
        borderRadius: "var(--radius-lg)",
        background: "var(--bt-red-bg)",
        color: "var(--bt-red-ink)",
        fontSize: "var(--fs-sm)",
      }}
    >
      <AlertCircle size={12} style={{ flexShrink: 0, marginTop: 3 }} aria-hidden />
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
          title={job.source_path}
        >
          {fileName(job.source_path)}
        </div>
        {job.error && (
          <div
            style={{
              fontSize: "var(--fs-xs)",
              opacity: 0.85,
              lineHeight: 1.4,
              marginTop: 2,
            }}
          >
            {job.error.slice(0, 160)}
          </div>
        )}
      </div>
    </div>
  );
}
