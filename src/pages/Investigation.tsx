import { useCallback, useEffect, useMemo, useState } from "react";
import { entities as mockEntities } from "../data/mock";
import { useAppStore } from "../store";
import { useBackendStore } from "../store/backend";
import { apiListCriminals, apiListCaseEntities, apiListCaseRelationships, apiListCases, type CaseRead, type EntityRead, type CriminalProfile } from "../services/api";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList, StatRow } from "../components/HudPrimitives";
import { IntelligenceSummary, PriorityPanel, RecommendationList, GapList } from "../components/IntelligenceUi";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";

type AnyEntity = { id: string; type: string; name: string; risk?: number; confidence?: number; aliases?: string[]; relationships?: number; sources?: number; lastActivity?: string };

export function Investigation() {
  const backend = useBackendStore((s) => s.mode);
  const [cases, setCases] = useState<CaseRead[]>([]);
  const [caseKey, setCaseKey] = useState<string | null>(null);
  const [entities, setEntities] = useState<EntityRead[]>([]);
  const [relationships, setRelationships] = useState<number>(0);
  const [profiles, setProfiles] = useState<CriminalProfile[]>([]);
  const [selected, setSelected] = useState<AnyEntity | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { selectedEntity, setSelectedEntity } = useAppStore();
  const { intel: caseIntel } = useCaseIntelligence(caseKey ?? "");

  const reload = useCallback(async (key: string) => {
    setLoading(true);
    setError(null);
    try {
      const [ents, rels, profs] = await Promise.all([
        apiListCaseEntities(key),
        apiListCaseRelationships(key),
        apiListCriminals({ limit: 100 }),
      ]);
      setEntities(ents);
      setRelationships(rels.length);
      setProfiles(profs.items);
      setSelected(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load case data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (backend !== "backend") return;
    apiListCases({ limit: 100 })
      .then((res) => {
        setCases(res.items);
        if (res.items.length > 0) {
          setCaseKey(res.items[0].case_number);
          void reload(res.items[0].case_number);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load cases"));
  }, [backend, reload]);

  const rows: AnyEntity[] = useMemo(() => {
    if (backend !== "backend") {
      return mockEntities.map((e) => ({
        id: e.id, type: e.type, name: e.name, risk: e.risk,
        confidence: e.confidence, aliases: e.aliases,
        relationships: e.relationships, lastActivity: e.lastActivity,
      }));
    }
    const merged: AnyEntity[] = entities.map((e) => ({
      id: e.entity_id, type: e.entity_type, name: e.name,
      confidence: Math.round(e.confidence * 100), sources: e.source_ids.length,
    }));
    for (const p of profiles) {
      merged.push({
        id: p.secret_id, type: p.profile_type, name: p.name,
        risk: p.risk_score, confidence: p.confidence,
        aliases: p.aliases,
      });
    }
    return merged;
  }, [backend, entities, profiles]);

  const activeCase = cases.find((c) => c.case_number === caseKey) ?? cases[0];

  if (backend !== "backend") {
    return (
      <HudPage className="investigation-page" title={activeCase?.case_number ?? "CASE-2026-0817"} subtitle={activeCase?.title ?? "Organized Network Analysis"} rightMeta={<><div>OFFLINE DEMO</div></>}>
        <div className="hud-investigation-layout">
          <HudCard label="Case graph" title="Network View" className="hud-investigation-list">
            <div className="table">
              {rows.map((e) => (
                <button key={e.id} className={`entity ${selectedEntity?.id === e.id ? "selected" : ""}`} onClick={() => setSelectedEntity(e as never)}>
                  <div>
                    <div>{e.name}</div>
                    <div className="meta">{e.type} · {e.id}</div>
                  </div>
                  {typeof e.risk === "number" && <div className="risk">Risk {e.risk}</div>}
                </button>
              ))}
            </div>
          </HudCard>
          <HudCard label="Entity profile" title={selectedEntity?.name ?? "No selection"} className="hud-investigation-profile">
            {selectedEntity && <HoloList items={[
              { label: "Entity type", value: selectedEntity.type },
              { label: "Risk score", value: String(selectedEntity.risk) },
              { label: "Aliases", value: (selectedEntity.aliases ?? []).join(", ") || "—" },
              { label: "Relationships", value: String(selectedEntity.relationships ?? 0) },
              { label: "Last activity", value: selectedEntity.lastActivity ?? "—" },
            ]} />}
          </HudCard>
        </div>
      </HudPage>
    );
  }

  return (
    <HudPage
      className="investigation-page"
      title="INVESTIGATIONS"
      subtitle="Relational case records and extracted entities"
      rightMeta={<>{loading ? <div>SYNCING</div> : <div>SYNCED</div>}<div>{entities.length} ENTITIES</div></>}
    >
      <div className="hud-investigation-layout">
        <HudCard label="Case selector" title="Open investigation" className="hud-investigation-list">
          <div className="stack" style={{ gap: 8 }}>
            <select className="control" value={caseKey ?? ""} onChange={(e) => { const k = e.target.value; setCaseKey(k); void reload(k); }}>
              {!cases.length && <option value="">No cases yet</option>}
              {cases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} — {c.title}</option>)}
            </select>
            {activeCase && (
              <div className="mini-list">
                <StatRow label="Priority" value={activeCase.priority} />
                <StatRow label="Status" value={activeCase.status} />
                <StatRow label="Created" value={new Date(activeCase.created_at).toLocaleDateString()} />
              </div>
            )}
            {error ? <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div> : null}
          </div>
          <h3 style={{ marginTop: 16 }}>Persisted relationships: {relationships}</h3>
        </HudCard>
        <HudCard label="Entity index" title={`Matched entities (${rows.length})`} className="hud-investigation-profile">
          <div className="table" style={{ maxHeight: 320, overflowY: "auto" }}>
            {rows.map((e) => (
              <button key={`${e.type}-${e.id}`} className={`entity ${selected?.id === e.id ? "selected" : ""}`} onClick={() => setSelected(e)}>
                <div>
                  <div>{e.name}</div>
                  <div className="meta">{e.type} · {e.id}{e.sources ? ` · ${e.sources} sources` : ""}</div>
                </div>
                {typeof e.risk === "number" && <div className="risk">Risk {e.risk}</div>}
              </button>
            ))}
            {!rows.length && <div className="meta">Upload and process a source to see extracted entities.</div>}
          </div>
        </HudCard>
      </div>
      {selected && (
        <HudCard label="Entity intelligence" title={selected.name} className="hud-investigation-layout">
          <div style={{ padding: 4 }}>
            <HoloList items={[
              { label: "Identifier", value: selected.id },
              { label: "Type", value: selected.type },
              { label: "Confidence", value: `${selected.confidence ?? 0}%` },
              { label: "Source references", value: String(selected.sources ?? 0) },
            ]} />
          </div>
        </HudCard>
      )}

      {caseIntel && (
        <div className="hud-investigation-layout" style={{ marginTop: 18 }}>
          <IntelligenceSummary intel={caseIntel} />
          <PriorityPanel title="Priority entities" items={caseIntel.entity_priorities} />
          <RecommendationList recs={caseIntel.recommendations} />
          <GapList gaps={caseIntel.evidence_gaps} />
        </div>
      )}
    </HudPage>
  );
}
