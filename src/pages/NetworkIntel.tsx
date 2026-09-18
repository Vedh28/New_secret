import { useMemo, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { NetworkGraph } from "../components/NetworkGraph";
import { PriorityPanel, RecommendationList, PotentialLinksList, TemporalChangesList } from "../components/IntelligenceUi";
import { useBackendStore } from "../store/backend";
import { apiRecordLinkDecision } from "../services/api";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";
import { useCaseGraph } from "../hooks/useCaseGraph";
import { useCaseSelection } from "../services/useCaseSelection";

/**
 * Network Intelligence.
 *
 * STRICTLY CASE-SCOPED: the rendered graph is the selected case's persisted
 * entities + relationships (`GET /cases/{caseKey}/graph`); community count,
 * DNA and potential links come from the same case intelligence snapshot.
 * The global projection is never merged into a case screen.
 */
export function NetworkIntel() {
  const mode = useBackendStore((s) => s.mode);
  const online = mode === "backend";
  const { caseKey } = useCaseSelection();
  const [refreshKey, setRefreshKey] = useState(0);
  const { intel } = useCaseIntelligence(caseKey, refreshKey);
  const { graph, loading: graphLoading, error: graphError } = useCaseGraph(caseKey, refreshKey);

  const decide = async (link: { source: string; target: string }, decision: "CONFIRM" | "REJECT" | "DEFER") => {
    if (!online || !caseKey) return;
    try {
      await apiRecordLinkDecision(caseKey, link.source, link.target, decision);
      setRefreshKey((k) => k + 1);
    } catch { /* leave UI as-is on failure */ }
  };

  // Rank nodes by evidence-linked centrality approximation (degree).
  const hot = useMemo(() => {
    const degree: Record<string, number> = {};
    for (const edge of graph.edges) {
      degree[edge.source] = (degree[edge.source] ?? 0) + 1;
      degree[edge.target] = (degree[edge.target] ?? 0) + 1;
    }
    const ranked = graph.nodes
      .map((node) => ({ node, degree: degree[node.id] ?? 0 }))
      .filter((x) => x.degree > 0)
      .sort((a, b) => b.degree - a.degree)
      .slice(0, 4);
    return ranked;
  }, [graph]);

  // Influencers: highest investigation priority from the case intelligence snapshot.
  const influencers = useMemo(() => {
    const byId = new Map(graph.nodes.map((node) => [node.id, node]));
    return (intel?.entity_priorities ?? [])
      .filter((p) => byId.has(p.subject))
      .slice(0, 4)
      .map((p) => ({ node: byId.get(p.subject)!, priority: p.priority }));
  }, [intel, graph]);

  const peopleCount = graph.nodes.filter((node) => node.type?.toUpperCase() === "PERSON").length;
  const clusterCount = intel?.network_dna?.community_count ?? 0;

  const telemetry = [
    { label: "Top connected entity", value: hot[0]?.node.name ?? "Awaiting data" },
    { label: "Evidence coverage", value: `${intel?.network_dna?.evidence_coverage ?? 0}%` },
    { label: "Communities mapped", value: String(clusterCount) },
    { label: "People involved", value: String(peopleCount) },
  ];

  return (
    <HudPage
      title="NETWORK INTELLIGENCE"
      subtitle="High-density relationship analysis"
      rightMeta={
        <>
          <div>{online ? "GRAPH ONLINE" : "AWAITING DATA"}</div>
        </>
      }
    >
      <div className="hud-network-layout">
        <HudCard label="Graph overview" title="Network Telemetry" className="hud-network-controls">
          <div className="hud-network-telemetry">
            {telemetry.map((item) => (
              <div key={item.label}><span>{item.label}</span><strong>{item.value}</strong></div>
            ))}
          </div>
          {graphError && <div className="meta" style={{ marginTop: 8, color: "var(--red, #ff5f56)" }}>{graphError}</div>}
        </HudCard>

        <HudCard label="Graph surface" title="Network Mesh" className="hud-network-mesh">
          <div className="hud-net-graph">
            {graphLoading && !graph.nodes.length ? (
              <div className="meta">Loading case graph…</div>
            ) : (
              <NetworkGraph nodes={graph.nodes} edges={graph.edges} />
            )}
          </div>
        </HudCard>

        <div className="hud-network-side">
          <HudCard label="Entity details" title="Key Influencers">
            <HoloList
              items={influencers.map((entry, i) => ({
                label: `${String(i + 1).padStart(2, "0")}  ${entry.node.name}`,
                value: entry.priority.toFixed(1),
              }))}
            />
          </HudCard>
          <HudCard label="Pulse map" title="Hot nodes">
            <div className="mini-list">
              {hot.map((entry) => (
                <div key={entry.node.id} className="entity entity-tight">
                  <div>
                    <div>{entry.node.name}</div>
                    <div className="meta">{entry.node.type} · {entry.degree} links</div>
                  </div>
                  <div className="risk">{entry.degree}</div>
                </div>
              ))}
            </div>
          </HudCard>
          {intel && <PriorityPanel title="Priority targets" items={intel.entity_priorities} />}
          {intel && <TemporalChangesList changes={intel.temporal_changes} />}
          {intel && <PotentialLinksList links={intel.potential_links} decisions={intel.link_decisions} onDecision={online ? decide : undefined} />}
          {intel && <RecommendationList recs={intel.recommendations} />}
        </div>
      </div>
    </HudPage>
  );
}