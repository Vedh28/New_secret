import { useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";
import { apiListAudit, type AuditEntry } from "../services/api";

const DEMO_AUDIT: AuditEntry[] = [
  { id: 104, action: "Generated network analysis report", object_type: "report", object_id: "network_analysis", result: { status: "demo_ready" }, created_at: "2026-09-11T21:14:00+05:30" },
  { id: 103, action: "Ran what-if relationship simulation", object_type: "simulation", object_id: "N-4821", result: { connectivity_change: "+2.1%" }, created_at: "2026-09-11T21:08:00+05:30" },
  { id: 102, action: "Reviewed communication burst signal", object_type: "alert", object_id: "COMM_BURST", result: { score: 91 }, created_at: "2026-09-11T20:56:00+05:30" },
  { id: 101, action: "Opened investigation workspace", object_type: "case", object_id: "DEMO-CASE-001", result: { mode: "offline_demo" }, created_at: "2026-09-11T20:42:00+05:30" },
];

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    let active = true;
    const loadLocalDemoAudit = () => {
      try {
        const local = JSON.parse(localStorage.getItem("secret.demo.audit") ?? "[]") as AuditEntry[];
        if (active && local.length) setEntries((current) => [...local, ...current.filter((entry) => !local.some((item) => item.id === entry.id))].slice(0, 50));
      } catch { /* ignore malformed local demo history */ }
    };
    window.addEventListener("secret:audit-updated", loadLocalDemoAudit);
    apiListAudit(50)
      .then((res) => { if (!active) return; setEntries(res); setDemoMode(false); loadLocalDemoAudit(); })
      .catch(() => { if (!active) return; setEntries(DEMO_AUDIT); setDemoMode(true); loadLocalDemoAudit(); })
      .finally(() => active && setLoaded(true));
    return () => {
      active = false;
      window.removeEventListener("secret:audit-updated", loadLocalDemoAudit);
    };
  }, []);

  return (
    <HudPage
      title="AUDIT LOG"
      subtitle={demoMode ? "Append-only record · offline demo activity" : "Append-only record of significant actions"}
      rightMeta={<>{loaded ? <div>{entries.length} ENTRIES</div> : <div>LOADING</div>}</>}
    >
      <HudCard label="System log" title="Recent Actions" className="hud-audit-list">
        {entries.length ? (
          <div className="stack">
            {entries.map((e) => (
              <div key={e.id} className="entity entity-tight">
                <div>
                  <div>{e.action}</div>
                  <div className="meta">{e.object_type ?? "system"} · {e.object_id ?? "-"} · {new Date(e.created_at).toLocaleString()}</div>
                  {Object.keys(e.result).length > 0 && <div className="meta">Result: {Object.entries(e.result).map(([key, value]) => `${key}=${String(value)}`).join(" · ")}</div>}
                </div>
                <div className="risk">{e.id}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="meta">{loaded ? "No audit entries recorded yet in this environment." : "Loading audit log..."}</div>
        )}
      </HudCard>
    </HudPage>
  );
}
