// Main review surface — three columns: SpeakerList | TranscriptView | MetaPanel.
// A processing banner sits above the columns while a pipeline run is active
// for this meeting.

import { useEffect } from "react";
import { MetaPanel } from "../components/MetaPanel";
import { ProcessingBanner } from "../components/ProcessingBanner";
import { ProtocolView } from "../components/ProtocolView";
import { SpeakerList } from "../components/SpeakerList";
import { TranscriptView } from "../components/TranscriptView";
import { useMeetingStore } from "../state/useMeetingStore";

export function MeetingReview() {
  const view = useMeetingStore((s) => s.view);
  const meetingId = view.name === "review" ? view.meetingId : null;
  const loadProtocol = useMeetingStore((s) => s.loadProtocol);

  // Beim Öffnen nachsehen, ob für dieses Meeting schon ein Protokoll
  // vorliegt — es liegt als Datei im Meeting-Ordner, nicht in der DB.
  useEffect(() => {
    if (meetingId) void loadProtocol(meetingId);
  }, [meetingId, loadProtocol]);

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        height: "100%",
      }}
    >
      {meetingId && <ProcessingBanner meetingId={meetingId} />}
      {/* minHeight: 0 auf allen dreien — sonst bestimmt die längste Spalte
          (meist das Transkript) die Höhe, und weder Sprecherliste noch
          Transkript lassen sich scrollen. */}
      <div style={{ flex: 1, display: "flex", minWidth: 0, minHeight: 0 }}>
        <div style={{ width: 260, flexShrink: 0, minHeight: 0 }}>
          <SpeakerList />
        </div>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <ProtocolView />
          <div style={{ flex: 1, minHeight: 0 }}>
            <TranscriptView />
          </div>
        </div>
        <MetaPanel />
      </div>
    </div>
  );
}
