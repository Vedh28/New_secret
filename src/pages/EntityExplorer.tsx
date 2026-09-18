import { useEffect, useMemo, useState } from "react";
import { useBackendStore } from "../store/backend";
import { apiListCriminals, apiUpdateCaseEntity, type CriminalProfile } from "../services/api";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";
import { AnomalyList } from "../components/IntelligenceUi";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";
import { useCaseSelection } from "../services/useCaseSelection";
import { prototypeEntities } from "../data/prototypeCase";
import { useMapStore } from "../store/mapStore";

type Row = {
  id: string;
  type: string;
  name: string;
  risk?: number;
  confidence?: number;
  links?: number;
};

function parseCoordinate(value: string): number | undefined {
  const cleaned = value.trim().replace(/[°]/g, "");
  const match = cleaned.match(/^([-+]?\d+(?:\.\d+)?)\s*([NSEW])?$/i);
  if (!match) return undefined;
  const number = Number(match[1]);
  const direction = match[2]?.toUpperCase();
  if (!Number.isFinite(number)) return undefined;
  return direction === "S" || direction === "W" ? -Math.abs(number) : number;
}

export function EntityExplorer() {
  const backend = useBackendStore((s) => s.mode);
  const graph = useBackendStore((s) => s.graph);
  const [query, setQuery] = useState("");
  const [profiles, setProfiles] = useState<CriminalProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const { caseKey } = useCaseSelection();
  const { intel: caseIntel } = useCaseIntelligence(caseKey);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [resolvedName, setResolvedName] = useState("");
  const [evidenceIds, setEvidenceIds] = useState("");
  const [resolutionNote, setResolutionNote] = useState("");
  const [resolutionConfidence, setResolutionConfidence] = useState("80");
  const [locationName, setLocationName] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [savingResolution, setSavingResolution] = useState(false);
  const [resolutionMessage, setResolutionMessage] = useState<string | null>(null);
  const [resolvedNames, setResolvedNames] = useState<Record<string, string>>({});

  useEffect(() => {
    try {
      const saved = localStorage.getItem(`secret.identity-resolutions.${caseKey}`);
      setResolvedNames(saved ? JSON.parse(saved) as Record<string, string> : {});
    } catch {
      setResolvedNames({});
    }
  }, [caseKey]);

  useEffect(() => {
    if (backend !== "backend") return;
    apiListCriminals({ limit: 100 })
      .then((res) => setProfiles(res.items))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load entities"));
  }, [backend]);

  const rows: Row[] = useMemo(() => {
    if (backend !== "backend") {
      return prototypeEntities.map((entity) => ({
        id: entity.id,
        type: entity.type,
        name: entity.name,
        risk: entity.risk,
        confidence: entity.confidence,
        links: entity.relationships,
      }));
    }
    const map = new Map<string, Row>();
    for (const p of profiles) {
      map.set(p.secret_id, { id: p.secret_id, type: p.profile_type, name: p.name, risk: p.risk_score, confidence: p.confidence });
    }
    for (const n of graph.nodes) {
      const existing = map.get(n.id);
      map.set(n.id, { id: n.id, type: n.type, name: resolvedNames[n.id] ?? n.name, risk: typeof existing?.risk === "number" ? existing.risk : undefined, confidence: existing?.confidence ?? undefined, links: graph.edges.filter((e) => e.source === n.id || e.target === n.id).length });
    }
    return Array.from(map.values());
  }, [backend, profiles, graph, resolvedNames]);

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
    const entity = focusedEntity;
    setResolvedName(entity?.name ?? "");
    setEvidenceIds("");
    setResolutionNote("");
    setResolutionConfidence(String(entity?.confidence ?? 80));
    setLocationName("");
    setLatitude("");
    setLongitude("");
    setResolutionMessage(null);
  }, [selectedId]);

  const saveIdentityResolution = async () => {
    if (!selectedId || !resolvedName.trim()) return;
    if (locationName.trim() && (!latitude.trim() || !longitude.trim())) {
      setResolutionMessage("Enter both latitude and longitude before saving the location.");
      return;
    }
    const parsedLatitude = parseCoordinate(latitude);
    const parsedLongitude = parseCoordinate(longitude);
    if (locationName.trim() && (parsedLatitude === undefined || parsedLongitude === undefined)) {
      setResolutionMessage("Use decimal coordinates, for example 19.1761 N and 72.9477 E.");
      return;
    }
    if (backend !== "backend") {
      setResolutionMessage("Sign in to save identity resolution and evidence provenance.");
      return;
    }
    setSavingResolution(true);
    setResolutionMessage(null);
    try {
      await apiUpdateCaseEntity(caseKey, selectedId, {
        name: resolvedName.trim(),
        confidence: Math.max(0, Math.min(100, Number(resolutionConfidence) || 0)) / 100,
        source_ids: evidenceIds.split(",").map((id) => id.trim()).filter(Boolean),
        note: resolutionNote.trim() || undefined,
        location_name: locationName.trim() || undefined,
        latitude: parsedLatitude,
        longitude: parsedLongitude,
      });
      setResolvedNames((current) => {
        const next = { ...current, [selectedId]: resolvedName.trim() };
        localStorage.setItem(`secret.identity-resolutions.${caseKey}`, JSON.stringify(next));
        return next;
      });
      if (locationName.trim()) void useMapStore.getState().load("backend");
      setResolutionMessage("Identity resolved and audit entry recorded.");
    } catch (err) {
      setResolutionMessage(err instanceof Error ? err.message : "Could not resolve identity.");
    } finally {
      setSavingResolution(false);
    }
  };

  useEffect(() => {
    if (selectedId || !caseIntel?.entity_priorities.length) return;
    const highestPriority = [...caseIntel.entity_priorities].sort((a, b) => b.priority - a.priority)[0];
    if (rows.some((row) => row.id === highestPriority.subject)) setSelectedId(highestPriority.subject);
  }, [caseIntel, rows, selectedId]);

  return (
    <HudPage title="ENTITY EXPLORER" subtitle="Live entity registry + graph nodes" rightMeta={<><div>{filtered.length} RESULTS</div>{backend === "backend" ? <div>LIVE</div> : <div>AWAITING DATA</div>}</>}>
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
                <div className="entity-profile-links">
                  <div className="meta"><b>Potential links</b></div>
                  {caseIntel.potential_links.filter((l) => l.source === selectedId || l.target === selectedId).map((link) => <div key={`${link.source}-${link.target}`} className="entity entity-tight"><div><b>{link.source}</b> ↔ <b>{link.target}</b><div className="meta">{link.supporting_signals.slice(0, 2).join(" · ")}</div></div><div className="risk">{link.score.toFixed(0)}%</div></div>)}
                  {!caseIntel.potential_links.some((l) => l.source === selectedId || l.target === selectedId) && <div className="meta">No potential links for this entity.</div>}
                </div>
              </>
          ) : <div className="meta">
            {selectedId
              ? "Intelligence data is loading for this entity."
              : "Select an entity from the result matrix to inspect its intelligence."}
          </div>}
          {selectedId && <div className="entity-resolution-panel">
            <div className="meta"><b>Resolve identity</b></div>
            <div className="meta">Stable ID: <b>{selectedId}</b>. The original label stays in provenance.</div>
            <input className="control hud-search" value={resolvedName} onChange={(e) => setResolvedName(e.target.value)} placeholder="Known name" aria-label="Known name" />
            <input className="control hud-search" value={evidenceIds} onChange={(e) => setEvidenceIds(e.target.value)} placeholder="Evidence/source IDs, comma separated" aria-label="Evidence source IDs" />
            <input className="control hud-search" type="number" min="0" max="100" value={resolutionConfidence} onChange={(e) => setResolutionConfidence(e.target.value)} placeholder="Confidence %" aria-label="Resolution confidence" />
            <textarea className="control hud-search" value={resolutionNote} onChange={(e) => setResolutionNote(e.target.value)} placeholder="Why this identity is being resolved" aria-label="Resolution note" rows={3} />
            <div className="meta"><b>Add current location</b> (optional)</div>
            <input className="control hud-search" value={locationName} onChange={(e) => setLocationName(e.target.value)} placeholder="Location, area or city" aria-label="Entity location" />
            <div className="row">
              <input className="control hud-search" value={latitude} onChange={(e) => setLatitude(e.target.value)} placeholder="Latitude e.g. 19.1761 N" aria-label="Latitude" />
              <input className="control hud-search" value={longitude} onChange={(e) => setLongitude(e.target.value)} placeholder="Longitude e.g. 72.9477 E" aria-label="Longitude" />
            </div>
            <button className="cta" type="button" disabled={savingResolution || !resolvedName.trim() || Boolean(locationName.trim() && (!latitude.trim() || !longitude.trim()))} onClick={() => void saveIdentityResolution()}>
              {savingResolution ? "SAVING..." : "RESOLVE + ATTACH EVIDENCE"}
            </button>
            {resolutionMessage && <div className="meta" style={{ color: resolutionMessage.includes("recorded") ? "var(--green)" : "var(--amber)" }}>{resolutionMessage}</div>}
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
                    {typeof e.links === "number" ? `${e.links} ${e.links === 1 ? "link" : "links"}` : "No linked evidence"}
                    {typeof e.risk === "number" ? ` · Risk ${e.risk}` : ""}
                    {typeof e.confidence === "number" ? ` · Confidence ${e.confidence}%` : ""}
                  </div>
                </button>
              );
            })}
            {!filtered.length && <div className="meta">No entities found. Ingest a source to grow the registry.</div>}
          </div>
        </HudCard>
      </div>

    </HudPage>
  );
}
