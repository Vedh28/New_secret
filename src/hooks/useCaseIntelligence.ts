import { useEffect, useState } from "react";
import { useBackendStore } from "../store/backend";
import { apiCaseIntelligence, type CaseIntelligence } from "../services/api";
import { prototypeIntelligence, prototypeIntelligenceByCase } from "../data/prototypeCase";

/**
 * Fetch case intelligence for a caseKey. Falls back to a locally-composed
 * OfflineIntelligence derived deterministically from the demo corpus when the
 * backend is unavailable, so the intelligence experience never goes blank.
 */
export interface OfflineCaseIntelligence {
  caseNumber: string;
  detection: CaseIntelligence | null;
}

// Deterministic offline intelligence mirroring the backend engines.
const OFFLINE_INTELLIGENCE: CaseIntelligence = {
  case_id: 0,
  evidence_fusion: {},
  evidence: [],
  temporal_changes: [
    { kind: "NEW_REL", source: "P-0312", target: "O-1101", window: "", before: 0, after: 1, score: 15,
      explanation: "New MEMBER_OF relationship appeared after the split point." },
    { kind: "STRENGTHENED", source: "N-4821", target: "N-9044", window: "", before: 0, after: 5, score: 50,
      explanation: "Phone 4821↔9044 shows sustained activity." },
    { kind: "EMERGING_BRIDGE", source: "P-0421", target: "", window: "", before: 0, after: 2, score: 50,
      explanation: "P-0421 gained cross-community connections." },
  ],
  anomalies: [
    { kind: "COMM_BURST", entity_id: "N-4821", baseline: 1, observed: 5, deviation: 400, score: 91,
      timestamp: "2026-08-14T09:00", evidence: ["Phone 4821 initiated 5 calls in 1 hour"],
      explanation: "Unusual communication burst (investigative signal, not a finding)." },
    { kind: "TX_AMOUNT", entity_id: "A-4200->A-0182", baseline: 650000, observed: 2400000, deviation: 269,
      score: 82, timestamp: "2026-08-14T09:30", evidence: ["Transfer 2,400,000 vs median 650,000"],
      explanation: "High-value transfer flagged as unusual financial activity." },
  ],
  potential_links: [
    { source: "P-0421", target: "P-0312", score: 73,
      supporting_signals: ["Shared organization (1)", "Shared location (1)", "Common intermediary", "Temporal overlap"],
      contradictory_signals: [], evidence_ids: [], confidence: 0.73,
      explanation: "P-0421 ↔ P-0312 is a POTENTIAL relationship (not directly observed) supported by shared organization, location and an intermediary. Requires confirmation before treating as a link." },
  ],
  evidence_gaps: [
    { subject: "P-0421<->P-0312", known_evidence: ["Shared location", "Common intermediary"],
      missing_evidence: ["direct communication or transfer evidence", "independent confirmation from a second source type"],
      importance: 73, recommended_source: "CDR", window: "a 14-day observation window",
      explanation: "Before accepting P-0421-P-0312 as a link, obtain direct communication or transfer evidence. This would raise evidence confidence for the potential relationship." },
  ],
  network_dna: { density: 0.31, centralization: 0.73, community_count: 3, clustering: 0.0,
                 bridge_dependence: "HIGH", bridge_ratio: 0.3, temporal_volatility: 0.4,
                 communication_activity: "HIGH", transaction_anomaly: "MEDIUM", evidence_coverage: 78, fragmentation: 0.6 },
  entity_priorities: [
    { subject: "P-0421", priority: 88, factors: { centrality: 100, bridge_importance: 80 }, explanation: ["Network importance: +27", "Network bridge: +14"] },
    { subject: "N-4821", priority: 73, factors: { centrality: 70 }, explanation: ["Network importance: +21"] },
  ],
  relationship_priorities: [],
  recommendations: [
    { kind: "RELATIONSHIP", subject: "P-0421<->P-0312", priority: 88, info_gain: 81,
      reasoning: ["Connects two communities", "Multiple sources support the relationship"],
      evidence_ids: [], entity_ids: ["P-0421", "P-0312"], recommended_data: "CDR and location records between the pair",
      window: "review the relationship before validating" },
  ],
};

export function useCaseIntelligence(caseKey: string) {
  const backend = useBackendStore((s) => s.mode);
  const [intel, setIntel] = useState<CaseIntelligence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend === "backend" && caseKey) {
      setLoading(true);
      apiCaseIntelligence(caseKey)
        .then((data) => { setIntel(data); setError(null); })
        .catch((err) => { setError(err instanceof Error ? err.message : "Failed to load"); setIntel(null); })
        .finally(() => setLoading(false));
    } else if (backend !== "backend") {
      setIntel(prototypeIntelligenceByCase[caseKey] ?? prototypeIntelligence);
      setError(null);
    } else {
      setIntel(null);
    }
  }, [backend, caseKey]);

  return { intel, loading, error, offline: backend !== "backend", offlineIntel: prototypeIntelligenceByCase[caseKey] ?? prototypeIntelligence };
}
