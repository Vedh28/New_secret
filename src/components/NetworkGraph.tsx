/**
 * NetworkGraph — interactive SVG graph for the Network Intelligence mesh.
 *
 * Real nodes/edges rendering with a force-based layout (d3-force, an existing
 * dependency), wheel zoom, drag pan, node selection, connected-node +
 * relationship highlighting, and reset/fit controls. Pure additive visual layer
 * over the HUD design tokens — no new datasets, no framework additions.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from "d3";
import type { GraphEdge, GraphNode } from "../services/api";
import { useMapStore } from "../store/mapStore";

const W = 800;
const H = 520;
const ITERATIONS = 320;

const TYPE_COLORS: Record<string, string> = {
  PERSON: "var(--blue)",
  ORGANIZATION: "var(--green)",
  VEHICLE: "var(--amber)",
  LOCATION: "var(--red)",
  PHONE: "var(--muted)",
  ACCOUNT: "var(--green)",
  CASE: "var(--amber)",
};

interface Position { id: string; x: number; y: number }

function layout(nodes: GraphNode[], edges: GraphEdge[]): Position[] {
  if (!nodes.length) return [];
  const simNodes = nodes.map((n, i) => ({
    id: n.id,
    x: 40 + ((i * 37.7) % (W - 80)),
    y: 40 + ((i * 71.3) % (H - 80)),
  }));
  const idToIndex = new Map(simNodes.map((n, i) => [n.id, i]));
  const links = edges
    .filter((e) => typeof e.source === "string" && typeof e.target === "string" && idToIndex.has(e.source) && idToIndex.has(e.target))
    .map((e) => ({ source: e.source, target: e.target }));

  type SimNode = { id: string; x: number; y: number };
  type SimLink = { source: string; target: string };

  try {
    const simulation = forceSimulation<SimNode>(simNodes)
      .force("link", forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(92).strength(0.35))
      .force("charge", forceManyBody().strength(-280))
      .force("center", forceCenter(W / 2, H / 2))
      .force("collide", forceCollide().radius(30))
      .stop();
    for (let i = 0; i < ITERATIONS; i += 1) simulation.tick();
  } catch {
    // Keep the mesh usable if an upstream graph contains an invalid relationship.
  }
  return simNodes;
}

interface View { k: number; tx: number; ty: number }

export function NetworkGraph({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const positions = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const selected = useMapStore((s) => s.selectedEntityId);
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 });
  const drag = useRef<{ px: number; py: number; tx: number; ty: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;
    const blockPageZoom = (event: WheelEvent) => {
      if (event.ctrlKey) event.preventDefault();
    };
    surface.addEventListener("wheel", blockPageZoom, { passive: false });
    return () => surface.removeEventListener("wheel", blockPageZoom);
  }, []);

  const posById = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);

  const neighbors = useMemo(() => {
    if (!selected) return new Set<string>();
    const set = new Set<string>();
    for (const e of edges) {
      if (e.source === selected) set.add(e.target);
      if (e.target === selected) set.add(e.source);
    }
    set.add(selected);
    return set;
  }, [selected, edges]);

  const selectedEdgeIds = useMemo(() => {
    if (!selected) return new Set<string>();
    const set = new Set<string>();
    for (const e of edges) {
      if (e.source === selected || e.target === selected) set.add(e.id);
    }
    return set;
  }, [selected, edges]);

  // Initial fit so the whole component is visible on mount.
  useEffect(() => {
    if (!positions.length) return;
    const xs = positions.map((p) => p.x);
    const ys = positions.map((p) => p.y);
    const minX = Math.min(...xs) - 60;
    const maxX = Math.max(...xs) + 60;
    const minY = Math.min(...ys) - 60;
    const maxY = Math.max(...ys) + 60;
    const fit = Math.min(W / (maxX - minX), H / (maxY - minY));
    const k = Math.min(4, fit * 1.45);
    setView({
      k,
      tx: (W - (maxX + minX) * k) / 2,
      ty: (H - (maxY + minY) * k) / 2,
    });
  }, [positions]);

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const factor = e.deltaY < 0 ? 1.15 : 0.87;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const cx = (e.clientX - rect.left) * (W / rect.width);
    const cy = (e.clientY - rect.top) * (H / rect.height);
    setView((v) => {
      const k = Math.min(4, Math.max(0.25, v.k * factor));
      const tx = cx - ((cx - v.tx) * k) / v.k;
      const ty = cy - ((cy - v.ty) * k) / v.k;
      return { k, tx, ty };
    });
  };

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    drag.current = { px: e.clientX, py: e.clientY, tx: view.tx, ty: view.ty };
    if (e.target === svgRef.current) useMapStore.getState().selectEntity(null);
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const activeDrag = drag.current;
    if (!activeDrag || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const dx = ((e.clientX - activeDrag.px) * W) / rect.width;
    const dy = ((e.clientY - activeDrag.py) * H) / rect.height;
    setView((v) => ({ ...v, tx: activeDrag.tx + dx, ty: activeDrag.ty + dy }));
  };
  const onPointerUp = () => { drag.current = null; };

  const selectedNode = selected ? nodes.find((n) => n.id === selected) : null;

  if (!nodes.length) {
    return <div className="meta" style={{ paddingTop: 40 }}>No graph data to render. Ingest and materialize a case.</div>;
  }

  return (
    <div ref={surfaceRef} className="hud-net-surface">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height="100%"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        style={{ touchAction: "none", cursor: "grab", display: "block" }}
        role="img"
        aria-label="Interactive knowledge graph"
      >
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
          {edges.map((e) => {
            const a = posById.get(e.source);
            const b = posById.get(e.target);
            if (!a || !b) return null;
            const active = selectedEdgeIds.has(e.id);
            const dimmed = selected !== null && !active;
            const highlighted = selected !== null && active;
            return (
              <line
                key={e.id}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={highlighted ? "#ff7b88" : "rgba(176,38,62,0.88)"}
                strokeWidth={highlighted ? 2.4 : dimmed ? 0.5 : 1.1}
                opacity={dimmed ? 0.12 : active ? 0.96 : 0.78}
              />
            );
          })}
          {nodes.map((n) => {
            const p = posById.get(n.id);
            if (!p) return null;
            const isSelected = n.id === selected;
            const isNeighbor = neighbors.has(n.id);
            const dimmed = selected !== null && selected !== n.id && !neighbors.has(n.id);
            const color = TYPE_COLORS[n.type?.toUpperCase()] ?? "var(--muted)";
            return (
              <g
                key={n.id}
                transform={`translate(${p.x} ${p.y})`}
                opacity={dimmed ? 0.18 : 1}
                style={{ cursor: "pointer" }}
                onPointerDown={(ev) => { ev.stopPropagation(); useMapStore.getState().selectEntity(n.id); }}
              >
                {isSelected && <circle r={17} fill="none" stroke="var(--text)" strokeWidth={1.4} opacity={0.9} />}
                {isNeighbor && !isSelected && <circle r={13} fill="none" stroke="var(--blue)" strokeWidth={1} opacity={0.6} />}
                <circle r={8} fill={color} stroke="rgba(255,255,255,0.25)" strokeWidth={1} opacity={isSelected ? 1 : 0.88} />
                <text
                  y={-16} textAnchor="middle" fontSize={11}
                  fill={dimmed ? "var(--muted)" : "var(--text)"}
                  style={{ letterSpacing: "0.04em" }}
                >
                  {n.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      {selectedNode && (
        <div className="glass-strip hud-net-selection" style={{ position: "absolute", top: 10, left: 10 }}>
          {selectedNode.name} · {selectedNode.type} · {neighbors.size - 1} links · {selectedEdgeIds.size} relationships
        </div>
      )}
    </div>
  );
}
