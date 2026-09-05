import { useEffect, useMemo, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { NetworkGraph } from "../components/NetworkGraph";
import { PriorityPanel, RecommendationList, PotentialLinksList, TemporalChangesList } from "../components/IntelligenceUi";
import { useBackendStore } from "../store/backend";
import { apiCommunities } from "../services/api";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";
import { useCaseSelection } from "../services/useCaseSelection";

/**
 * Network Intelligence.
 *
 * The Network Mesh now renders the actual nodes/edges (interactive: zoom, pan,
 * node selection, connected-node + relationship highlighting, reset/fit). The
 * "clusters mapped" chip counts real communities: backend Louvain when online,
 * connected components of the synthetic graph when offline.
 */
function connectedComponents(count: number, edges: { source: string; target: string }[]): number {
  if (count === 0) return 0;
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    if (!parent.has(x)) parent.set(x, x);
    let root = x;
    while (parent.get(root) !== root) root = parent.get(root)!;
    return root;
  };
  const union = (a: string, b: string) => {
    const ra = find(a); const rb = find(b);
    if (ra !== rb) parent.set(rb, ra);
  };
  for (const e of edges) { find(e.source); find(e.target); union(e.source, e.target); }
  const withEdges = new Set(edges.flatMap((e) => [e.source, e.target]));
  return new Set([...parent.keys()].map(find)).size + Math.max(0, count - withEdges.size);
}

export function NetworkIntel() {
  const graph = useBackendStore((s) => s.graph);
  const mode = useBackendStore((s) => s.mode);
  const online = mode === "backend";
  const [clusterCount, setClusterCount] = useState(0);
  const { caseKey } = useCaseSelection();
  const { intel: caseIntel } = useCaseIntelligence(caseKey);

  // Rank nodes by risk to approximate influencer importance.
  const influencers = useMemo(() => {
    const scored = graph.nodes.map((node) => ({
      node,
      risk: (node.properties?.risk as number) ?? (node.properties?.risk_score as number) ?? 0,
    }));
    scored.sort((a, b) => b.risk - a.risk);
    return scored.slice(0, 4);
  }, [graph]);

  // Hot nodes: entities with the most connections.
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

  // Community count: real Louvain clusters when online, connected components
  // of the visible graph when offline. Never node count.
  useEffect(() => {
    if (online) {
      apiCommunities()
        .then((res) => setClusterCount(Number(res.count) || 0))
        .catch(() => setClusterCount(connectedComponents(graph.nodes.length, graph.edges)));
      return;
    }
    const ids = new Set(graph.nodes.map((n) => n.id));
    const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    setClusterCount(connectedComponents(ids.size, edges));
  }, [online, graph]);

  return (
    <HudPage
      title="NETWORK INTELLIGENCE"
      subtitle="High-density relationship analysis"
      rightMeta={
        <>
          <div>{online ? "GRAPH ONLINE" : "SYNTHETIC MODE"}</div>
          <div>{graph.nodes.length} NODES · {graph.edges.length} LINKS</div>
        </>
      }
    >
      <div className="hud-network-layout">
        <HudCard label="Filters" title="Signal Controls" className="hud-network-controls">
          <div className="filters hud-filters">
            <button className="pill">ENTITY TYPE</button>
            <button className="pill">RELATIONSHIP TYPE</button>
            <button className="pill">TIME RANGE</button>
            <button className="pill">RISK LEVEL</button>
            <button className="pill">CONFIDENCE</button>
          </div>
          <div className="hud-network-mini">
            <div className="hud-network-orbit" />
            <div className="hud-network-axis">
              <span>Clustering</span>
              <span>Propagation</span>
              <span>Stability</span>
            </div>
          </div>
        </HudCard>

        <HudCard label="Graph surface" title="Network Mesh" className="hud-network-mesh">
          <div className="hud-net-graph">
            <NetworkGraph nodes={graph.nodes} edges={graph.edges} />
          </div>
          <div className="hud-network-overlay">
            <div className="glass-strip">{clusterCount} clusters mapped</div>
            <div className="glass-strip">{graph.edges.length} active paths</div>
          </div>
        </HudCard>

        <div className="hud-network-side">
          <HudCard label="Entity details" title="Key Influencers">
            <HoloList
              items={influencers.map((entry, i) => ({
                label: `${String(i + 1).padStart(2, "0")}  ${entry.node.name}`,
                value: entry.risk.toFixed(1),
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
          {caseIntel && <PriorityPanel title="Priority targets" items={caseIntel.entity_priorities} />}
          {caseIntel && <TemporalChangesList changes={caseIntel.temporal_changes} />}
          {caseIntel && <PotentialLinksList links={caseIntel.potential_links} />}
          {caseIntel && <RecommendationList recs={caseIntel.recommendations} />}
        </div>
      </div>
    </HudPage>
  );
}
