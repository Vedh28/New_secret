/**
 * InvestigativeLeadsPanel — create, open, review and transition investigative
 * leads (Phase 12/17). A lead is an INVESTIGATIVE HYPOTHESIS, not a finding.
 */
import { useCallback, useEffect, useState } from "react";
import { HudCard } from "./HudPrimitives";
import { apiCaseLeads, apiCreateLead, apiUpdateLead, type LeadRead, type Recommendation } from "../services/api";

// Canonical hypothesis lifecycle shared with potential-link decisions.
const STATUSES = ["REVIEWING", "ANALYST_CONFIRMED", "REJECTED", "DEFERRED"];

export function InvestigativeLeadsPanel({ caseKey, recommendations }: { caseKey: string; recommendations: Recommendation[] }) {
  const [leads, setLeads] = useState<LeadRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!caseKey) return;
    setLoading(true);
    try {
      setLeads(await apiCaseLeads(caseKey));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load leads");
    } finally {
      setLoading(false);
    }
  }, [caseKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const createFromRecommendation = async (r: Recommendation) => {
    try {
      await apiCreateLead(caseKey, {
        kind: r.kind,
        title: `${r.kind} — ${r.subject}`,
        priority: r.priority,
        info_gain: r.info_gain,
        entity_ids: r.entity_ids,
        recommended_action: r.recommended_data,
        explanation: r.reasoning.join(" · "),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  };

  const transition = async (lead: LeadRead, status: string) => {
    try {
      await apiUpdateLead(caseKey, lead.id, { status });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  };

  return (
    <HudCard label="Investigative leads" title="Actionable hypotheses">
      {recommendations.length > 0 && (
        <div className="meta" style={{ marginBottom: 8 }}>Promote a recommendation to a lead:</div>
      )}
      {recommendations.slice(0, 4).map((r) => (
        <button key={`${r.kind}-${r.subject}`} className="pill" style={{ margin: "0 6px 6px 0" }}
                onClick={() => void createFromRecommendation(r)}>
          + {r.subject}
        </button>
      ))}
      {error && <div className="meta" style={{ color: "var(--red, #ff5f56)", marginTop: 8 }}>{error}</div>}
      <div className="stack" style={{ marginTop: 10 }}>
        {leads.map((lead) => (
          <div key={lead.id} className="entity entity-tight">
            <div>
              <div><span className="tag">{lead.status}</span> {lead.title}</div>
              {lead.explanation && <div className="meta">{lead.explanation}</div>}
              {lead.recommended_action && <div className="meta">Action: {lead.recommended_action}</div>}
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              {STATUSES.filter((s) => s !== lead.status).map((s) => (
                <button key={s} className="pill" onClick={() => void transition(lead, s)}>{s}</button>
              ))}
            </div>
          </div>
        ))}
        {!leads.length && !loading && <div className="meta">No investigative leads yet. Promote a recommendation above.</div>}
      </div>
    </HudCard>
  );
}