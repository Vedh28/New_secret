import { useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, Crosshair, ShieldAlert } from "lucide-react";
import { prototypeEntities } from "../data/prototypeCase";
import { useBackendStore } from "../store/backend";
import { useMapStore } from "../store/mapStore";
import type { CaseMarker } from "../types";

type PriorityItem = {
  marker: CaseMarker;
  score: number;
  leadName: string;
  leadRisk: number | null;
  leadReason: string;
};

const priorityWeights: Record<string, number> = {
  CRITICAL: 100,
  HIGH: 78,
  MEDIUM: 52,
  LOW: 28,
};

function calculatePriority(marker: CaseMarker, leadRisk: number | null): number {
  const base = priorityWeights[marker.priority.toUpperCase()] ?? 20;
  const active = /ACTIVE|OPEN|INVESTIGAT/.test(marker.status.toUpperCase()) ? 10 : 0;
  const locations = Math.min(12, marker.locations.length * 1.7);
  const entities = Math.min(10, marker.entityIds.length * 1.25);
  const observations = Math.min(8, marker.locations.reduce((sum, location) => sum + (location.observationCount ?? 0), 0) * 0.7);
  const sources = Math.min(7, marker.locations.reduce((sum, location) => sum + (location.sourceCount ?? 0), 0) * 0.35);
  const unresolvedLead = marker.entityIds.some((id) => id.toUpperCase().startsWith("UNKNOWN")) ? 5 : 0;
  const leadSignal = leadRisk === null ? 0 : Math.min(8, leadRisk / 12);
  return Math.min(100, Math.round(base + active + locations + entities + observations + sources + unresolvedLead + leadSignal));
}

function topLead(marker: CaseMarker, graphNodes: ReturnType<typeof useBackendStore.getState>["graph"]["nodes"]): { name: string; risk: number | null; reason: string } {
  const graphById = new Map(graphNodes.map((node) => [node.id, node]));
  const prototypeById = new Map(prototypeEntities.map((entity) => [entity.id, entity]));
  const candidates = marker.locations.flatMap((location) => location.entityIds.map((id, index) => ({
    id,
    displayName: location.entityNames?.[index] ?? location.entityNames?.[0],
  })));
  const unique = [...new Map(candidates.map((candidate) => [candidate.id, candidate])).values()]
    .filter((candidate) => !candidate.id.toUpperCase().startsWith("CAR-") && !candidate.id.toUpperCase().startsWith("LOCATION"));
  const ranked = unique.map((candidate) => {
    const node = graphById.get(candidate.id);
    const entity = prototypeById.get(candidate.id);
    const rawRisk = node?.properties?.risk ?? entity?.risk;
    const risk = typeof rawRisk === "number" ? rawRisk : null;
    return { ...candidate, name: candidate.displayName || node?.name || entity?.name || candidate.id, risk };
  }).sort((a, b) => (b.risk ?? 0) - (a.risk ?? 0));
  const lead = ranked[0];
  if (!lead) return { name: "Awaiting linked person", risk: null, reason: "No person entity is linked to this case yet." };
  return {
    name: lead.name,
    risk: lead.risk,
    reason: lead.risk === null ? "Linked person requires identity and risk enrichment." : "Highest linked person risk signal in this case.",
  };
}

export function TopPriorityPanel() {
  const markers = useMapStore((state) => state.markers);
  const selectedCaseId = useMapStore((state) => state.selectedCaseId);
  const graphNodes = useBackendStore((state) => state.graph.nodes);
  const [flippedCase, setFlippedCase] = useState<string | null>(null);

  const priorities = useMemo<PriorityItem[]>(() => markers.map((marker) => {
    const lead = topLead(marker, graphNodes);
    return { marker, score: calculatePriority(marker, lead.risk), leadName: lead.name, leadRisk: lead.risk, leadReason: lead.reason };
  }).sort((a, b) => b.score - a.score || b.marker.locations.length - a.marker.locations.length).slice(0, 3), [graphNodes, markers]);

  if (!markers.length) return null;

  return (
    <aside className="top-priority-dock" aria-label="Calculated top priority cases">
      <div className="top-priority-heading">
        <div>
          <div className="hud-label">TOP PRIORITY</div>
          <strong>Cases requiring attention</strong>
        </div>
        <span className="top-priority-live"><ShieldAlert size={13} /> CALCULATED</span>
      </div>
      <div className="top-priority-list">
        {priorities.map((item, index) => {
          const isFlipped = flippedCase === item.marker.caseId;
          const isSelected = selectedCaseId === item.marker.caseId;
          return (
            <button
              key={item.marker.caseId}
              type="button"
              className={`priority-flip-card ${isFlipped ? "is-flipped" : ""} ${isSelected ? "is-selected" : ""}`}
              onClick={() => {
                useMapStore.getState().selectCase(item.marker.caseId);
                setFlippedCase(isFlipped ? null : item.marker.caseId);
              }}
              aria-label={`${item.marker.title}. Click to ${isFlipped ? "show case details" : "show top lead"}.`}
            >
              <span className="priority-flip-inner">
                <span className="priority-face priority-front">
                  <span className="priority-rank">0{index + 1}<small> / {priorities.length}</small></span>
                  <span className="priority-face-copy">
                    <span className="priority-case-id">{item.marker.caseId}</span>
                    <strong>{item.marker.title}</strong>
                    <span className="priority-metrics"><b>{item.score}</b> PRIORITY SCORE <i>{item.marker.locations.length} LOCATIONS</i></span>
                  </span>
                  <ArrowRight className="priority-arrow" size={15} />
                </span>
                <span className="priority-face priority-back">
                  <span className="priority-back-kicker"><Crosshair size={13} /> TOP LEAD CRIMINAL</span>
                  <strong>{item.leadName}</strong>
                  <span>{item.leadRisk === null ? "RISK SIGNAL PENDING" : `RISK SIGNAL ${item.leadRisk}/100`}</span>
                  <small>{item.leadReason}</small>
                  <ArrowLeft className="priority-arrow" size={15} />
                </span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="top-priority-hint">Select a case to reveal its linked locations · click again for lead</div>
    </aside>
  );
}
