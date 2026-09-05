import { useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { apiCaseCommunications, type CommsResponse } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";

const EMPTY: CommsResponse = { total_communications: 0, top_contacts: [], flows: [], bursts: [] };
const DEMO_CASES = [
  { case_number: "CASE-2026-0817", title: "Network Bridge Review" },
  { case_number: "CASE-2026-0742", title: "Orion Contact Cluster" },
  { case_number: "CASE-2026-0631", title: "Financial Activity Sweep" },
];
const OFFLINE_COMMS: CommsResponse = {
  total_communications: 13,
  top_contacts: [
    { entity_id: "P-2041", count: 5 },
    { entity_id: "P-7712", count: 4 },
    { entity_id: "N-4821", count: 2 },
    { entity_id: "N-9044", count: 2 },
  ],
  flows: [
    { source: "P-2041", target: "P-7712", count: 4 },
    { source: "P-2041", target: "N-4821", count: 3 },
    { source: "P-7712", target: "N-9044", count: 2 },
    { source: "N-4821", target: "N-9044", count: 2 },
  ],
  bursts: [
    { entity_id: "P-2041", window: "14 Aug 2026 · 09:00", count: 6 },
    { entity_id: "P-7712", window: "14 Aug 2026 · 09:00", count: 4 },
  ],
};
const DEMO_COMMS_BY_CASE: Record<string, CommsResponse> = {
  "CASE-2026-0742": {
    total_communications: 9,
    top_contacts: [{ entity_id: "O-1101", count: 4 }, { entity_id: "P-2041", count: 3 }, { entity_id: "N-4821", count: 2 }],
    flows: [
      { source: "O-1101", target: "P-2041", count: 4 },
      { source: "P-2041", target: "N-4821", count: 3 },
      { source: "O-1101", target: "N-9044", count: 2 },
    ],
    bursts: [{ entity_id: "O-1101", window: "13 Aug 2026 · 18:00", count: 5 }],
  },
  "CASE-2026-0631": {
    total_communications: 6,
    top_contacts: [{ entity_id: "A-4200", count: 3 }, { entity_id: "P-7712", count: 2 }, { entity_id: "A-0182", count: 1 }],
    flows: [
      { source: "A-4200", target: "A-0182", count: 3 },
      { source: "P-7712", target: "A-4200", count: 2 },
      { source: "A-0182", target: "N-9044", count: 1 },
    ],
    bursts: [{ entity_id: "A-4200", window: "12 Aug 2026 · 11:00", count: 3 }],
  },
};

export function CommunicationsPage() {
  const { backend, cases, caseKey, setCaseKey } = useCaseSelection();
  const displayCases = cases.length ? cases : DEMO_CASES;
  const activeCaseKey = caseKey || DEMO_CASES[0].case_number;
  const [data, setData] = useState<CommsResponse>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend !== "backend") {
      setData(DEMO_COMMS_BY_CASE[activeCaseKey] ?? OFFLINE_COMMS);
      setError(null);
      return;
    }
    if (!caseKey) return;
    apiCaseCommunications(caseKey)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, [backend, caseKey, activeCaseKey]);

  return (
    <HudPage
      title="COMMUNICATION ANALYSIS"
      subtitle={backend === "backend" ? "Derived from persisted CDR relationships" : "Call and message cluster relationships"}
      rightMeta={<><div>{data.total_communications} LINKS</div><div>{backend === "backend" ? "LIVE" : "OFFLINE DEMO"}</div></>}
    >
      <div className="hud-explorer-layout">
        <HudCard label="Case" title="Investigation selector" className="hud-explorer-search">
          <select className="control hud-search" value={caseKey || displayCases[0].case_number} onChange={(e) => setCaseKey(e.target.value)}>
            {displayCases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
          </select>
          {error && <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div>}
        </HudCard>
        <HudCard label="Traffic" title="Top contacts" className="hud-explorer-grid">
          <HoloList items={data.top_contacts.map((c, i) => ({ label: c.entity_id, value: `${c.count} contacts${i === 0 ? " · HUB" : ""}` }))} />
          {!data.top_contacts.length && <div className="meta">No CALLED relationships persisted yet.</div>}
        </HudCard>
      </div>
      {data.bursts.length > 0 && (
        <HudCard label="Temporal" title="Unusual communication bursts">
          <div className="hud-search-hints">
            {data.bursts.slice(0, 8).map((b) => (
              <span key={`${b.entity_id}-${b.window}`} className="glass-strip">
                {b.entity_id} @ {b.window} · {b.count}
              </span>
            ))}
          </div>
        </HudCard>
      )}
      {data.flows.length > 0 && (
        <HudCard label="Flows" title="Caller → receiver">
          <div className="table" style={{ maxHeight: 320, overflowY: "auto" }}>
            {data.flows.map((f) => (
              <div key={`${f.source}-${f.target}`} className="entity entity-tight">
                <div>
                  <div><b>{f.source}</b> → <b>{f.target}</b></div>
                  <div className="meta">count {f.count}</div>
                </div>
              </div>
            ))}
          </div>
        </HudCard>
      )}
    </HudPage>
  );
}
