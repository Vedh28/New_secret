import { useEffect, useMemo, useState } from "react";
import { entities as mockEntities } from "../data/mock";
import { useBackendStore } from "../store/backend";
import { apiListCriminals, type CriminalProfile } from "../services/api";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";
import { AnomalyList, PotentialLinksList, PriorityPanel } from "../components/IntelligenceUi";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";
import { useCaseSelection } from "../services/useCaseSelection";

type Row = {
  id: string;
  type: string;
  name: string;
  risk?: number;
  confidence?: number;
  links?: number;
};

export function EntityExplorer() {
  const backend = useBackendStore((s) => s.mode);
  const graph = useBackendStore((s) => s.graph);
  const [query, setQuery] = useState("");
  const [profiles, setProfiles] = useState<CriminalProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const { caseKey } = useCaseSelection();
  const { intel: caseIntel } = useCaseIntelligence(caseKey);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (backend !== "backend") return;
    apiListCriminals({ limit: 100 })
      .then((res) => setProfiles(res.items))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load entities"));
  }, [backend]);

  const rows: Row[] = useMemo(() => {
    if (backend !== "backend") {
      return mockEntities.map((e) => ({ id: e.id, type: e.type, name: e.name, risk: e.risk, confidence: e.confidence, links: e.relationships }));
    }
    const map = new Map<string, Row>();
    for (const p of profiles) {
      map.set(p.secret_id, { id: p.secret_id, type: p.profile_type, name: p.name, risk: p.risk_score, confidence: p.confidence });
    }
    for (const n of graph.nodes) {
      const existing = map.get(n.id);
      map.set(n.id, { id: n.id, type: n.type, name: n.name, risk: typeof existing?.risk === "number" ? existing.risk : undefined, confidence: existing?.confidence ?? undefined, links: graph.edges.filter((e) => e.source === n.id || e.target === n.id).length });
    }
    return Array.from(map.values());
  }, [backend, profiles, graph]);

  const filtered = useMemo(
    () => rows
      .filter((e) => `${e.name} ${e.type} ${e.id}`.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => {
        const priorityA = caseIntel?.entity_priorities.find((item) => item.subject === a.id)?.priority ?? -1;
        const priorityB = caseIntel?.entity_priorities.find((item) => item.subject === b.id)?.priority ?? -1;
        return priorityB - priorityA;
      }),
    [rows, query, caseIntel],
  );
  const focusedEntity = selectedId ? rows.find((row) => row.id === selectedId) : null;
  const focusedLinks = selectedId
    ? graph.edges.filter((edge) => edge.source === selectedId || edge.target === selectedId).length
    : 0;

  useEffect(() => {
    if (selectedId || !caseIntel?.entity_priorities.length) return;
    const highestPriority = [...caseIntel.entity_priorities].sort((a, b) => b.priority - a.priority)[0];
    if (rows.some((row) => row.id === highestPriority.subject)) setSelectedId(highestPriority.subject);
  }, [caseIntel, rows, selectedId]);

  return (
    <HudPage title="ENTITY EXPLORER" subtitle={backend === "backend" ? "Live entity registry + graph nodes" : "Synthetic demo registry"} rightMeta={<><div>{filtered.length} RESULTS</div>{backend === "backend" ? <div>LIVE</div> : <div>DEMO</div>}</>}>
      <div className="hud-explorer-layout">
        <div className="hud-explorer-sidebar">
          <HudCard label="Search console" title="Entity Query" className="hud-explorer-search">
            <input className="control hud-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search entity, identifier, organization..." />
            {error ? <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div> : null}
          </HudCard>
          <HudCard label="Entity intelligence" title={selectedId ?? "Select an entity"} className="hud-explorer-intelligence">
          {caseIntel && selectedId ? (
              <>
                <div className="entity-intelligence-profile">
                  <div><span>Profile</span><strong>{focusedEntity?.name ?? selectedId}</strong></div>
                  <div><span>Type</span><strong>{focusedEntity?.type ?? "PERSON"}</strong></div>
                  <div><span>Risk</span><strong>{focusedEntity?.risk ?? "-"}</strong></div>
                  <div><span>Links</span><strong>{focusedEntity?.links ?? focusedLinks}</strong></div>
                  <div className="meta">Active investigation · Last activity: 14 Aug 2026, 09:30</div>
                </div>
                <div className="meta">
                  Focus entity {selectedId}. Priority and anomaly signals below derive from the
                  unified intelligence engine.
                </div>
                {caseIntel.anomalies?.filter((a) => a.entity_id.includes(selectedId)).length ? (
                  <AnomalyList compact anomalies={caseIntel.anomalies.filter((a) => a.entity_id.includes(selectedId))} />
                ) : <div className="meta">No anomaly signals for this entity.</div>}
              </>
          ) : <div className="meta">
            {selectedId
              ? "Intelligence data is loading for this entity."
              : "Select an entity from the result matrix to inspect its intelligence."}
          </div>}
          </HudCard>
        </div>
        <HudCard label="Result matrix" title="Matched Entities" className="hud-explorer-grid">
          <div className="hud-entity-grid">
            {filtered.map((e) => {
              const priority = caseIntel?.entity_priorities.find((item) => item.subject === e.id)?.priority;
              return (
                <button
                  className={`hud-card hud-mini-card${selectedId === e.id ? " is-selected" : ""}`}
                  key={`${e.type}-${e.id}`}
                  onClick={() => setSelectedId(e.id)}
                  style={{ textAlign: "left", cursor: "pointer" }}
                >
                  <div className="hud-label">{e.type}</div>
                  <h3>{e.name}</h3>
                  {typeof priority === "number" && <span className="entity-priority-badge">Priority {priority}</span>}
                  <div className="meta">
                    {e.id}
                    {typeof e.risk === "number" ? ` · Risk ${e.risk}` : ""}
                    {typeof e.confidence === "number" ? ` · Confidence ${e.confidence}%` : ""}
                    {typeof e.links === "number" ? ` · ${e.links} links` : ""}
                  </div>
                </button>
              );
            })}
            {!filtered.length && <div className="meta">No entities found. Ingest a source to grow the registry.</div>}
          </div>
        </HudCard>
      </div>

      {caseIntel && selectedId && (
        <div className="hud-explorer-layout" style={{ marginTop: 18 }}>
          <PriorityPanel title="By priority" items={caseIntel.entity_priorities.filter((p) => p.subject === selectedId)} />
          <PotentialLinksList links={caseIntel.potential_links.filter((l) => l.source === selectedId || l.target === selectedId)} />
        </div>
      )}
    </HudPage>
  );
}
