/**
 * Intelligence UI atoms (Phase 16-17).
 *
 * HUD-native presentational components that render intelligence-engine output.
 * All values come from the CaseIntelligence object (live API or offline
 * synthetic) — nothing is hardcoded here.
 */
import type { Anomaly, CaseIntelligence, EvidenceGap, NetworkDNA, PotentialLink, PriorityScore, Recommendation, TemporalChange } from "../services/api";
import { HudCard, HoloList, StatRow } from "./HudPrimitives";

export function DnaPanel({ dna }: { dna: NetworkDNA }) {
  if (!dna) return null;
  return (
    <HudCard label="Network DNA" title="Structural fingerprint">
      <HoloList items={[
        { label: "Density", value: dna.density.toFixed(2) },
        { label: "Centralization", value: dna.centralization.toFixed(2) },
        { label: "Communities", value: String(dna.community_count) },
        { label: "Clustering", value: dna.clustering.toFixed(2) },
        { label: "Bridge dependence", value: dna.bridge_dependence, accent: dna.bridge_dependence === "HIGH" ? "risk" : "" },
        { label: "Temporal volatility", value: dna.temporal_volatility.toFixed(2) },
        { label: "Communication", value: dna.communication_activity },
        { label: "Transaction anomaly", value: dna.transaction_anomaly },
        { label: "Evidence coverage", value: `${dna.evidence_coverage}%` },
        { label: "Fragmentation", value: dna.fragmentation.toFixed(2) },
      ]} />
    </HudCard>
  );
}

export function PriorityPanel({ title, items }: { title: string; items: PriorityScore[] }) {
  if (!items?.length) return null;
  return (
    <HudCard label="Investigation priority" title={title}>
      <div className="stack">
        {items.map((p) => (
          <div key={p.subject} className="entity entity-tight">
            <div>
              <div>{p.subject}</div>
              <div className="meta">{p.explanation.join(" · ") || "—"}</div>
            </div>
            <div className="risk">{p.priority.toFixed(0)}</div>
          </div>
        ))}
      </div>
    </HudCard>
  );
}

export function AnomalyList({ anomalies, compact = false }: { anomalies: Anomaly[]; compact?: boolean }) {
  if (!anomalies?.length) return null;
  const content = (
    <div className="stack">
      {anomalies.slice(0, 6).map((a, i) => (
        <div key={`${a.kind}-${a.entity_id}-${i}`} className="alert high">
          <div>
            <div className="tag">{a.kind} · score {a.score}</div>
            <div>{a.explanation}</div>
            <div className="meta">{a.entity_id}</div>
          </div>
        </div>
      ))}
    </div>
  );
  if (compact) return <div className="anomaly-list-compact">{content}</div>;
  return (
    <HudCard label="Anomaly intelligence" title="Unusual investigative signals">
      {content}
    </HudCard>
  );
}

export function PotentialLinksList({ links, onClick }: { links: PotentialLink[]; onClick?: (l: PotentialLink) => void }) {
  if (!links?.length) return null;
  return (
    <HudCard label="Hidden link discovery" title="Potential relationships">
      <div className="stack">
        {links.slice(0, 6).map((l) => (
          <button key={`${l.source}-${l.target}`} className="entity entity-tight" onClick={() => onClick?.(l)}>
            <div>
              <div><b>{l.source}</b> ↔ <b>{l.target}</b></div>
              <div className="meta">{l.supporting_signals.slice(0, 2).join(" · ")}</div>
            </div>
            <div className="risk">{l.score.toFixed(0)}</div>
          </button>
        ))}
      </div>
    </HudCard>
  );
}

export function RecommendationList({ recs }: { recs: Recommendation[] }) {
  if (!recs?.length) return null;
  return (
    <HudCard label="Next best action" title="What to investigate next">
      <div className="stack">
        {recs.map((r, i) => (
          <div key={`${r.kind}-${r.subject}`} className="entity entity-tight">
            <div>
              <div><span className="tag">#{i + 1} {r.kind}</span><b> {r.subject}</b></div>
              <div className="meta">{r.reasoning.slice(0, 2).join(" · ")}</div>
              {r.recommended_data && <div className="meta">Data: {r.recommended_data}</div>}
            </div>
            <div className="risk">P {r.priority.toFixed(0)} · G {r.info_gain.toFixed(0)}</div>
          </div>
        ))}
      </div>
    </HudCard>
  );
}

export function GapList({ gaps }: { gaps: EvidenceGap[] }) {
  if (!gaps?.length) return null;
  return (
    <HudCard label="Evidence gaps" title="What we don't know yet">
      <div className="stack">
        {gaps.slice(0, 6).map((g) => (
          <div key={g.subject} className="entity entity-tight">
            <div>
              <div><b>{g.subject}</b></div>
              <div className="meta">Missing: {g.missing_evidence.join(" · ")}</div>
              <div className="meta">Recommended: {g.recommended_source} — {g.window}</div>
            </div>
            <div className="risk">{g.importance.toFixed(0)}</div>
          </div>
        ))}
      </div>
    </HudCard>
  );
}

export function TemporalChangesList({ changes }: { changes: TemporalChange[] }) {
  if (!changes?.length) return null;
  return (
    <HudCard label="Temporal intelligence" title="What changed over time">
      <div className="stack">
        {changes.slice(0, 6).map((c, i) => (
          <div key={`${c.kind}-${c.source}-${i}`} className="entity entity-tight">
            <div>
              <div><span className="tag">{c.kind}</span> {c.source}{c.target ? ` ↔ ${c.target}` : ""}</div>
              <div className="meta">{c.explanation}</div>
            </div>
          </div>
        ))}
      </div>
    </HudCard>
  );
}

export function IntelligenceSummary({ intel }: { intel: CaseIntelligence }) {
  if (!intel) return null;
  const edge = intel.network_dna?.bridge_dependence ?? "LOW";
  return (
    <HudCard label="Case intelligence" title="Operational readout">
      <HoloList items={[
        { label: "Communities", value: String(intel.network_dna?.community_count ?? 0) },
        { label: "Anomalies", value: String(intel.anomalies?.length ?? 0) },
        { label: "Potential links", value: String(intel.potential_links?.length ?? 0) },
        { label: "Evidence gaps", value: String(intel.evidence_gaps?.length ?? 0) },
        { label: "Bridge dependence", value: edge, accent: edge === "HIGH" ? "risk" : "" },
        { label: "Recommendations", value: String(intel.recommendations?.length ?? 0) },
      ]} />
    </HudCard>
  );
}
