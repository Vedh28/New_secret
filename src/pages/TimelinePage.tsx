import { useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";
import { TemporalChangesList, AnomalyList } from "../components/IntelligenceUi";
import { apiCaseTimeline, type TimelineEvent } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";

export function TimelinePage() {
  const { backend, cases, caseKey, setCaseKey } = useCaseSelection();
  const { intel } = useCaseIntelligence(caseKey);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend !== "backend" || !caseKey) {
      setEvents([]);
      return;
    }
    apiCaseTimeline(caseKey)
      .then(setEvents)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, [backend, caseKey]);

  return (
    <HudPage
      title="TIMELINE"
      subtitle={backend === "backend" ? "Forensic chronological reconstruction + network evolution" : "Offline demo"}
      className="timeline-page"
      rightMeta={<><div>{events.length} EVENTS</div>{backend === "backend" ? <div>LIVE</div> : <div>DEMO</div>}</>}
    >
      {backend === "backend" && (
        <HudCard label="Case" title="Investigation selector" className="hud-timeline-selector">
          <select className="control hud-search" value={caseKey} onChange={(e) => setCaseKey(e.target.value)}>
            {cases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
          </select>
          {error && <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div>}
        </HudCard>
      )}
      <div className="hud-timeline-layout" style={{ marginTop: 16 }}>
        <HudCard label="Event sequence" title="Forensic chronology" className="hud-timeline-main">
          <div className="timeline-rail">
            {(events.length ? events : (intel?.temporal_changes ?? [])).map((e: any, i) => {
              const summary = e.summary ?? e.explanation ?? "";
              const ts = e.timestamp ?? "";
              const loc = e.location ?? "";
              const tag = e.source_id ?? e.kind ?? "EVENT";
              return (
                <div key={`${tag}-${i}`} className="timeline-row">
                  <div className="timeline-dot" />
                  <div className="timeline-card">
                    <div className="tag">{tag}</div>
                    <div>{summary}</div>
                    <div className="meta">
                      {ts ? new Date(ts).toLocaleString() : e.source && e.target ? `${e.source} ↔ ${e.target}` : "untimed"}
                      {loc ? ` · ${loc}` : ""}
                    </div>
                  </div>
                </div>
              );
            })}
            {!events.length && backend === "backend" && !(intel?.temporal_changes?.length) &&
              <div className="meta">No events yet — ingest sources for this case.</div>}
          </div>
        </HudCard>
        <div className="hud-timeline-side" style={{ display: "grid", gap: 16 }}>
          {intel && <TemporalChangesList changes={intel.temporal_changes} />}
          {intel && <AnomalyList anomalies={backend === "backend" ? intel.anomalies.filter((a) => a.kind !== "LOCATION") : intel.anomalies} />}
        </div>
      </div>
    </HudPage>
  );
}
