import { useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { apiAskAssistant, type AssistantResponse, type IntelligenceResponse } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";

function PotentialLine({ rel }: { rel: { source: string; target: string; kind: string; confidence: number } }) {
  return (
    <div className="entity entity-tight">
      <div>
        <div><b>{rel.source}</b> ↔ <b>{rel.target}</b></div>
        <div className="meta">
          <span className={`tag ${rel.kind === "POTENTIAL" ? "" : ""}`}>{rel.kind}</span>
          {" "}{Math.round((rel.confidence || 0) * 100)}%
        </div>
      </div>
    </div>
  );
}

function StructuredPanels({ s }: { s: IntelligenceResponse }) {
  return (
    <div className="hud-assistant-results" style={{ display: "grid", gap: 14 }}>
      {/* Summary / key findings */}
      <HudCard label="Assistant" title={s.summary || s.query}>
        {s.key_findings.length > 0 && (
          <HoloList items={s.key_findings.map((k) => ({ label: k.label, value: k.detail }))} />
        )}
        {s.anomalies.length > 0 && (
          <div className="stack" style={{ marginTop: 10 }}>
            <div className="meta"><b>Anomalies detected</b></div>
            {s.anomalies.slice(0, 5).map((a, i) => (
              <div key={i} className="alert high">
                <div><div className="tag">ANOMALY</div><div>{a}</div></div>
              </div>
            ))}
          </div>
        )}
      </HudCard>

      {/* Relationships + potential */}
      {s.relationships.length > 0 && (
        <HudCard label="Relationships" title={`Observed & potential links (${s.relationships.length})`}>
          <div className="stack">
            {s.relationships.map((r, i) => <PotentialLine key={i} rel={r} />)}
          </div>
        </HudCard>
      )}

      {/* Evidence gaps */}
      {s.evidence_gaps.length > 0 && (
        <HudCard label="Evidence gaps" title="What is missing">
          <div className="stack">
            {s.evidence_gaps.slice(0, 5).map((g, i) => <div key={i} className="meta">• {g}</div>)}
          </div>
        </HudCard>
      )}

      {/* Next best action */}
      {s.next_best_action && (
        <HudCard label="Next best action" title="What to examine next">
          <div className="stack">
            <div><b>{s.next_best_action.subject}</b> — {s.next_best_action.kind}</div>
            <HoloList items={[
              { label: "Priority", value: Math.round(s.next_best_action.priority).toString() },
              { label: "Information gain", value: Math.round(s.next_best_action.info_gain).toString() },
            ]} />
            {s.next_best_action.reasoning.length > 0 && (
              <div className="stack">
                <div className="meta"><b>Why?</b></div>
                {s.next_best_action.reasoning.map((r, i) => <div key={i} className="meta">• {r}</div>)}
              </div>
            )}
            {s.next_best_action.recommended_data && (
              <div className="meta">Recommended data: {s.next_best_action.recommended_data}</div>
            )}
          </div>
        </HudCard>
      )}
    </div>
  );
}

export function AssistantPage() {
  const { backend, caseKey } = useCaseSelection();
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AssistantResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = backend === "backend" ? await apiAskAssistant(question, caseKey) : demoAssistant(question);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Assistant unavailable");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <HudPage
      title="INTELLIGENCE ASSISTANT"
      subtitle={backend === "backend" ? "Evidence-grounded, structured case intelligence" : "Structured demo intelligence"}
      rightMeta={<><div>STRUCTURED</div>{backend === "backend" ? <div>LIVE</div> : <div>DEMO</div>}</>}
    >
      <div className="hud-assistant-layout">
        <HudCard label="Query console" title="Ask an investigative question">
          <input
            className="control hud-search"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder='e.g. "Show connections of P-0421", "potential links", "anomalies", "case overview"'
          />
          <div className="hud-search-hints">
            {["connections of P-0421", "potential links", "anomalies", "case overview"].map((hint) => <button key={hint} className="glass-strip hud-assistant-hint" onClick={() => setQuestion(hint)}>TRY: {hint}</button>)}
          </div>
          <button className="cta" onClick={ask} disabled={loading} style={{ marginTop: 14 }}>
            {loading ? "ANALYZING..." : "ASK ASSISTANT"}
          </button>
        </HudCard>

        {error ? (
          <HudCard label="System" title="Unavailable">
            <div className="meta">{error}</div>
          </HudCard>
        ) : !result ? (
          <HudCard label="Assistant status" title="Ready for analysis" className="hud-assistant-welcome">
            <div className="hud-assistant-orbit"><span /><i /><i /><i /></div>
            <div className="meta">Ask about relationships, potential links, anomalies or the case overview. The assistant returns structured evidence, gaps and a next-best action.</div>
            <div className="hud-assistant-status-grid"><div><span>MODE</span><strong>{backend === "backend" ? "LIVE" : "DEMO"}</strong></div><div><span>SOURCES</span><strong>02</strong></div><div><span>OUTPUT</span><strong>STRUCTURED</strong></div></div>
          </HudCard>
        ) : null}

        {result?.structured ? (
          <StructuredPanels s={result.structured} />
        ) : result ? (
          <HudCard label="Assistant" title={result.question}>
            <p>{result.answer}</p>
            <div className="hud-search-hints" style={{ marginTop: 12 }}>
              {result.source_ids.length ? (
                result.source_ids.map((id) => <span key={id} className="glass-strip">{id}</span>)
              ) : (
                <span className="glass-strip">No supporting source</span>
              )}
            </div>
          </HudCard>
        ) : null}
      </div>
    </HudPage>
  );
}

function demoAssistant(question: string): AssistantResponse {
  const q = question.toLowerCase();
  const isConnections = q.includes("connection") || q.includes("relationship") || q.includes("link");
  const isAnomaly = q.includes("anomal") || q.includes("signal") || q.includes("burst");
  const relationships = isConnections ? [
    { source: "P-0421", target: "P-0312", kind: "POTENTIAL", confidence: 0.73 },
    { source: "N-4821", target: "N-9044", kind: "CONFIRMED", confidence: 0.91 },
  ] : [];
  const anomalies = isAnomaly ? [
    "COMM_BURST: N-4821 shows 5 calls in one hour versus a baseline of 1.",
    "TX_AMOUNT: A-4200 to A-0182 transfer is 2.4M versus a 650K median.",
  ] : ["COMM_BURST: N-4821 is the highest-scoring investigative signal."];
  const summary = isConnections
    ? "Two relationship signals were found: one potential link requiring confirmation and one confirmed communication link."
    : isAnomaly
      ? "Two unusual signals need review. These are investigative signals, not findings."
      : "The demo case contains three communities, high bridge dependence and two priority signals requiring evidence validation.";
  const structured: IntelligenceResponse = {
    type: isConnections ? "relationships" : isAnomaly ? "anomalies" : "case_overview",
    query: question,
    summary,
    key_findings: [{ label: "Network", detail: "3 communities connected through a small number of bridge entities." }, { label: "Coverage", detail: "Synthetic demo case: every entity has a recorded source reference; independent confirmation is still required." }],
    entities: [{ id: "P-0421", type: "Person", name: "P-0421", priority: 88 }, { id: "N-4821", type: "Phone", name: "N-4821", priority: 73 }],
    relationships,
    anomalies,
    evidence: ["Shared location", "Common intermediary", "Communication activity"],
    evidence_gaps: ["Direct communication or transfer evidence for P-0421 ↔ P-0312", "Independent confirmation from a second source type"],
    next_best_action: { kind: "RELATIONSHIP", subject: "P-0421 ↔ P-0312", priority: 88, info_gain: 81, reasoning: ["Connects two communities", "Multiple sources support the potential relationship"], recommended_data: "CDR and location records", window: "14-day observation window" },
    source_ids: ["DEMO-NETWORK-01", "DEMO-SIGNAL-02"],
    found: true,
  };
  return { question, answer: summary, source_ids: structured.source_ids, found: true, structured };
}
