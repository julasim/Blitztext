// Main review surface — three columns: SpeakerList | TranscriptView | MetaPanel.

import { MetaPanel } from "../components/MetaPanel";
import { SpeakerList } from "../components/SpeakerList";
import { TranscriptView } from "../components/TranscriptView";

export function MeetingReview() {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        minWidth: 0,
        height: "100%",
      }}
    >
      <div style={{ width: 260, flexShrink: 0 }}>
        <SpeakerList />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <TranscriptView />
      </div>
      <MetaPanel />
    </div>
  );
}
