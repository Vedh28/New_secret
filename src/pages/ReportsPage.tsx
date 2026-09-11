import { useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";
import { apiGenerateReport, apiListReports, apiRecordAudit, downloadReport, type ReportMeta, type ReportResponse } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";

const MODULES: { report_type: string; label: string }[] = [
  { report_type: "investigation_summary", label: "Investigation Summary" },
  { report_type: "entity_intelligence", label: "Entity Intelligence Report" },
  { report_type: "network_analysis", label: "Network Analysis Report" },
  { report_type: "transaction_analysis", label: "Transaction Analysis" },
  { report_type: "communication_analysis", label: "Communication Analysis" },
];

const DEMO_REPORTS: Record<string, { summary: string; metrics: [string, string][]; sections: [string, string][] }> = {
  investigation_summary: {
    summary: "A consolidated view of the current investigation, priority entities and evidence gaps.",
    metrics: [["Priority entities", "06"], ["Open evidence gaps", "03"], ["High-risk signals", "04"]],
    sections: [["Executive readout", "The network contains a small number of high-leverage entities that should be reviewed first."], ["Recommended focus", "Validate the strongest cross-community relationships before expanding the investigation." ]],
  },
  entity_intelligence: {
    summary: "Entity-level risk, confidence and relationship context for the most relevant subjects.",
    metrics: [["Entities ranked", "12"], ["High-risk entities", "04"], ["Avg confidence", "89%"]],
    sections: [["Risk concentration", "The highest-risk subjects also carry the strongest bridge or coordination signals."], ["Validation need", "Confirm identity resolution and independently verify the top-ranked profiles." ]],
  },
  network_analysis: {
    summary: "Structural analysis of communities, bridges and relationship density across the investigation graph.",
    metrics: [["Communities", "03"], ["Bridge dependence", "HIGH"], ["Graph coverage", "78%"]],
    sections: [["Network structure", "Three communities are connected through a limited number of high-importance bridge entities."], ["Operational implication", "Removing or validating a bridge relationship can materially change investigative priority." ]],
  },
  transaction_analysis: {
    summary: "Transaction patterns and unusual value movements requiring analyst review.",
    metrics: [["Transactions screened", "946"], ["Unusual patterns", "07"], ["High-value flags", "03"]],
    sections: [["Signal summary", "A small cluster of high-value transfers is driving the current transaction anomaly score."], ["Next check", "Compare counterparties, timing and source reliability before treating the pattern as meaningful." ]],
  },
  communication_analysis: {
    summary: "Communication activity, burst patterns and cross-community contact signals.",
    metrics: [["Signals reviewed", "2.8K"], ["Communication bursts", "05"], ["Cross-community links", "02"]],
    sections: [["Activity summary", "Recent communication bursts connect otherwise separate parts of the investigation graph."], ["Next check", "Review the burst window against location and transaction evidence for corroboration." ]],
  },
};

export function ReportsPage() {
  const { backend, cases, caseKey, setCaseKey } = useCaseSelection();
  const [moduleType, setModuleType] = useState("network_analysis");
  const [generating, setGenerating] = useState(false);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [meta, setMeta] = useState<ReportMeta[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [demoGeneratedAt, setDemoGeneratedAt] = useState<string | null>(null);
  const [demoHistory, setDemoHistory] = useState<string[]>([]);
  const demoReport = DEMO_REPORTS[moduleType];

  useEffect(() => {
    try { setDemoHistory(JSON.parse(localStorage.getItem("secret.demo.reports") ?? "[]")); } catch { setDemoHistory([]); }
  }, []);

  const generateDemo = () => {
    const generatedAt = new Date().toISOString();
    setDemoGeneratedAt(generatedAt);
    const next = [generatedAt, ...demoHistory].slice(0, 10);
    setDemoHistory(next);
    localStorage.setItem("secret.demo.reports", JSON.stringify(next));
    const audit = { id: Date.now(), action: `Generated ${moduleType} report`, object_type: "report", object_id: moduleType, result: { mode: "offline_demo" }, created_at: generatedAt };
    const previous = JSON.parse(localStorage.getItem("secret.demo.audit") ?? "[]") as unknown[];
    localStorage.setItem("secret.demo.audit", JSON.stringify([audit, ...previous].slice(0, 50)));
    window.dispatchEvent(new Event("secret:audit-updated"));
  };

  const downloadDemo = () => {
    if (!demoReport) return;
    const downloadedAt = new Date().toISOString();
    const label = MODULES.find((m) => m.report_type === moduleType)?.label ?? moduleType;
    const content = [
      "SECRET INTELLIGENCE REPORT",
      label,
      `Generated: ${demoGeneratedAt ? new Date(demoGeneratedAt).toLocaleString() : new Date().toLocaleString()}`,
      "",
      "SUMMARY",
      demoReport.summary,
      "",
      "KEY METRICS",
      ...demoReport.metrics.map(([key, value]) => `${key}: ${value}`),
      "",
      ...demoReport.sections.flatMap(([heading, body]) => [heading.toUpperCase(), body, ""]),
      "OFFLINE DEMO REPORT - VERIFY AGAINST LIVE CASE DATA BEFORE OPERATIONAL USE",
    ].join("\n");
    const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `secret-${moduleType}-${new Date().toISOString().slice(0, 10)}.txt`;
    link.click();
    URL.revokeObjectURL(url);
    const audit = { id: Date.now(), action: `Downloaded ${moduleType} report`, object_type: "report", object_id: moduleType, result: { format: "TXT", mode: "offline_demo" }, created_at: downloadedAt };
    const previous = JSON.parse(localStorage.getItem("secret.demo.audit") ?? "[]") as unknown[];
    localStorage.setItem("secret.demo.audit", JSON.stringify([audit, ...previous].slice(0, 50)));
    window.dispatchEvent(new Event("secret:audit-updated"));
  };

  const downloadLiveReport = () => {
    if (!report) return;
    downloadReport(report);
    void apiRecordAudit({ action: "Downloaded report", object_type: "report", object_id: report.id, result: { report_type: report.report_type, format: "PDF" } }).catch(() => undefined);
  };

  useEffect(() => {
    if (backend !== "backend") return;
    apiListReports()
      .then(setMeta)
      .catch(() => setMeta([]));
  }, [backend]);

  const generate = async () => {
    setError(null);
    setGenerating(true);
    try {
      const res = await apiGenerateReport({
        report_type: moduleType,
        case_number: caseKey || undefined,
        title: `${moduleType} — ${caseKey || "case"}`,
      });
      setReport(res);
      setMeta((prev) => [{ id: res.id, report_type: res.report_type, title: res.title, generated_at: res.generated_at, generated_by: res.generated_by, sections: res.sections.length }, ...prev]);
      void apiRecordAudit({ action: "Generated report", object_type: "report", object_id: res.id, result: { report_type: res.report_type, sections: res.sections.length } }).catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report generation failed");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <HudPage
      title="REPORTS"
      subtitle={backend === "backend" ? "Generated from live application state" : "Offline demo"}
      rightMeta={<>{report ? <div>EXPORT READY</div> : <div>STANDBY</div>}{backend === "backend" ? <div>LIVE</div> : <div>DEMO</div>}</>}
    >
      <div className="hud-reports-layout">
        <HudCard label="Report modules" title="Editorial Pack" className="hud-reports-list">
          <div className="stack">
            {MODULES.map((m) => (
              <button key={m.report_type} className={`entity entity-tight ${moduleType === m.report_type ? "selected" : ""}`} onClick={() => setModuleType(m.report_type)}>
                <div>
                  <div>{m.label}</div>
                  <div className="meta">{m.report_type}</div>
                </div>
              </button>
            ))}
            {backend === "backend" && (
              <select className="control hud-search" value={caseKey} onChange={(e) => setCaseKey(e.target.value)}>
                {cases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
              </select>
            )}
          </div>
        </HudCard>
        <HudCard label="Report preview" title="Composite Output" className="hud-reports-preview">
          {backend !== "backend" && demoReport ? (
            <div className="hud-report-canvas">
              <div className="hud-report-canvas-head"><span>DEMO PREVIEW</span><strong>{MODULES.find((m) => m.report_type === moduleType)?.label}</strong></div>
              <p>{demoReport.summary}</p>
              <div className="hud-report-metrics">
                {demoReport.metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
              </div>
              <div className="hud-report-sections">
                {demoReport.sections.map(([heading, body]) => <div key={heading} className="glass-strip"><b>{heading}</b><div className="meta">{body}</div></div>)}
              </div>
              <div className="meta hud-report-note">Connect the backend to generate and download a report from live case data.</div>
              <div className="hud-report-actions">
                <button className="cta" onClick={generateDemo}>{demoGeneratedAt ? "REPORT GENERATED" : "GENERATE REPORT"}</button>
                <button className="pill" onClick={downloadDemo}>DOWNLOAD REPORT</button>
              </div>
              {demoGeneratedAt && <div className="meta">Generated {new Date(demoGeneratedAt).toLocaleString()} · offline demo snapshot</div>}
              {demoHistory.length > 0 && <div className="meta">Report history: {demoHistory.length} generated snapshot{demoHistory.length === 1 ? "" : "s"} stored locally.</div>}
            </div>
          ) : <div className="hud-surface-grid hud-surface-grid-alt" />}
          {backend === "backend" ? (
            <>
              <button className="cta hud-report-cta" onClick={generate} disabled={generating || !caseKey}>
                {generating ? "GENERATING..." : "GENERATE REPORT"}
              </button>
              {error && <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div>}
              {report && (
                <div className="stack" style={{ marginTop: 12 }}>
                  <div className="meta">{report.title} · {new Date(report.generated_at).toLocaleString()}</div>
                  <button className="cta" onClick={downloadLiveReport}>DOWNLOAD PDF</button>
                  <div className="stack" style={{ maxHeight: 260, overflowY: "auto" }}>
                    {report.sections.map((s) => (
                      <div key={s.heading} className="glass-strip"><b>{s.heading}</b><div className="meta">{s.body}</div></div>
                    ))}
                  </div>
                </div>
              )}
              {meta.length > 0 && (
                <div className="stack" style={{ marginTop: 12 }}>
                  <div className="meta">Previously generated:</div>
                  {meta.slice(0, 5).map((m) => <div key={m.id} className="meta">{m.title} · {m.sections} sections</div>)}
                </div>
              )}
            </>
          ) : null}
        </HudCard>
      </div>
    </HudPage>
  );
}
