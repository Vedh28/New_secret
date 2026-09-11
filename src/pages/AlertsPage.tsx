import { useCallback, useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";
import { alerts as mockAlerts } from "../data/mock";
import { apiCaseAlerts, apiGenerateAlerts, apiUpdateAlert, type AlertRead } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";

const FILTERS = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"] as const;

const DEMO_ALERTS: AlertRead[] = mockAlerts.map((alert, index) => ({
  id: 9000 + index,
  case_id: null,
  profile_id: null,
  severity: alert.severity,
  status: index === 0 ? "NEW" : "REVIEWING",
  score: 91 - index * 9,
  title: alert.title,
  description: "Synthetic indicator generated from the offline intelligence feed.",
  source_ids: [`DEMO-${String(index + 1).padStart(2, "0")}`],
  confidence: 0.86 - index * 0.04,
  reviewed_by: null,
  reviewed_at: null,
  created_at: `2026-09-11T${alert.time}+05:30`,
}));

export function AlertsPage() {
  const { backend, cases, caseKey, setCaseKey } = useCaseSelection();
  const [alerts, setAlerts] = useState<AlertRead[]>([]);
  const [filter, setFilter] = useState<string>("ALL");
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async (key: string) => {
    try {
      setAlerts(await apiCaseAlerts(key));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load alerts");
    }
  }, []);

  const runGenerate = async () => {
    if (!caseKey) return;
    setGenerating(true);
    try {
      const res = await apiGenerateAlerts(caseKey);
      await load(caseKey);
      if (res.created === 0) setError("No new indicators above threshold (deduplicated).");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const transition = async (alert: AlertRead, status: string) => {
    if (backend !== "backend") {
      setAlerts((current) => current.map((item) => item.id === alert.id ? { ...item, status } : item));
      return;
    }
    await apiUpdateAlert(caseKey, alert.id, status);
    await load(caseKey);
  };

  useEffect(() => {
    if (backend === "backend" && caseKey) void load(caseKey);
    else if (backend !== "backend") setAlerts(DEMO_ALERTS);
  }, [backend, caseKey, load]);

  const list = alerts.filter((a) => filter === "ALL" || a.severity === filter);
  const severityCounts = FILTERS.slice(1).map((severity) => ({
    severity,
    count: alerts.filter((alert) => alert.severity === severity).length,
  }));

  return (
    <HudPage
      title="ALERT CENTER"
      subtitle={backend === "backend" ? "Indicator alerts computed from persisted analytics" : "Offline demo · synthetic intelligence feed"}
      rightMeta={<><div>{list.length} SIGNALS</div>{backend === "backend" ? <div>LIVE</div> : <div>DEMO</div>}</>}
    >
      <div className="hud-alert-layout">
        <HudCard label="Alert queue" title={backend === "backend" ? "Severity Filter" : "Synthetic mode"} className="hud-alert-filter">
          <div className="filters hud-filters">
            {FILTERS.map((f) => <button key={f} className={`pill ${filter === f ? "selected" : ""}`} onClick={() => setFilter(f)}>{f}{f === "ALL" ? ` · ${alerts.length}` : ` · ${alerts.filter((alert) => alert.severity === f).length}`}</button>)}
          </div>
          <div className="hud-alert-visual" aria-label={`${list.length} active signals`}>
            <div className="hud-alert-scan" />
            <div className="hud-alert-orbit hud-alert-orbit-one"><i /><i /><i /></div>
            <div className="hud-alert-orbit hud-alert-orbit-two"><i /><i /></div>
            <div className="hud-alert-core"><span>{list.length}</span><small>ACTIVE SIGNALS</small></div>
            <div className="hud-alert-wave" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
          </div>
          <div className="hud-alert-breakdown">
            {severityCounts.map(({ severity, count }) => <div key={severity}><span>{severity}</span><strong>{count}</strong></div>)}
          </div>
          {backend === "backend" && (
            <>
              <select className="control hud-search" value={caseKey} onChange={(e) => { setCaseKey(e.target.value); void load(e.target.value); }}>
                {cases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
              </select>
              <button className="cta" onClick={runGenerate} disabled={generating || !caseKey} style={{ marginTop: 8 }}>
                {generating ? "SCANNING..." : "GENERATE ALERT INDICATORS"}
              </button>
            </>
          )}
        </HudCard>
        <HudCard label="Alert stream" title="Incoming Signals" className="hud-alert-stream">
          <div className="stack">
            {list.length ? (
              list.map((a) => (
                <div key={a.id} className={`alert ${a.severity.toLowerCase()}`}>
                  <div>
                    <div className="tag">{a.severity} · {a.status} · score {a.score}</div>
                    <div>{a.title}</div>
                    {a.description && <div className="meta">{a.description}</div>}
                    <div className="meta">Sources: {a.source_ids.join(", ") || "—"} · confidence {a.confidence}</div>
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {a.status === "NEW" && <button className="pill" onClick={() => void transition(a, "REVIEWING")}>REVIEW</button>}
                    {a.status !== "DISMISSED" && <button className="pill" onClick={() => void transition(a, "DISMISSED")}>DISMISS</button>}
                    {a.status !== "RESOLVED" && <button className="pill" onClick={() => void transition(a, "RESOLVED")}>RESOLVE</button>}
                  </div>
                </div>
              ))
            ) : <div className="meta">No indicator alerts match this severity filter.</div>}
            {error && <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div>}
          </div>
        </HudCard>
      </div>
    </HudPage>
  );
}
