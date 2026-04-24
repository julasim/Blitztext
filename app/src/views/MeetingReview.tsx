// Main review surface — three columns: SpeakerList | TranscriptView | MetaPanel.
// A processing banner sits above the columns while a pipeline run is active
// for this meeting.

import { MetaPanel } from "../components/MetaPanel";
import { ProcessingBanner } from "../components/ProcessingBanner";
import { SpeakerList } from "../components/SpeakerList";
import { TranscriptView } from "../components/TranscriptView";
import { useMeetingStore } from "../state/useMeetingStore";

export function MeetingReview() {
  const view = useMeetingStore((s) => s.view);
  const meetingId = view.name === "review" ? view.meetingId : null;

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
      <div style={{ flex: 1, display: "flex", minWidth: 0 }}>
        <div style={{ width: 260, flexShrink: 0 }}>
          <SpeakerList />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <TranscriptView />
        </div>
        <MetaPanel />
      </div>
    </div>
  );
}
