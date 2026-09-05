import { useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList, StatRow } from "../components/HudPrimitives";
import { apiCaseTransactions, type TransResponse } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";

const EMPTY: TransResponse = { total_transactions: 0, total_amount: 0, flows: [], top_senders: [] };
const DEMO_CASES = [
  { case_number: "CASE-2026-0817", title: "Network Bridge Review" },
  { case_number: "CASE-2026-0742", title: "Orion Contact Cluster" },
  { case_number: "CASE-2026-0631", title: "Financial Activity Sweep" },
];
const OFFLINE_TRANSACTIONS: TransResponse = {
  total_transactions: 12,
  total_amount: 3445000,
  top_senders: [
    { account_id: "A-4200", total_amount: 1630000, count: 6 },
    { account_id: "A-0182", total_amount: 865000, count: 3 },
    { account_id: "P-2041", total_amount: 950000, count: 3 },
  ],
  flows: [
    { source: "A-4200", target: "A-0182", count: 4, total_amount: 1240000 },
    { source: "A-4200", target: "N-4821", count: 2, total_amount: 390000 },
    { source: "A-0182", target: "P-2041", count: 3, total_amount: 865000 },
    { source: "P-2041", target: "A-4200", count: 2, total_amount: 740000 },
    { source: "P-2041", target: "A-0182", count: 1, total_amount: 210000 },
  ],
};
const DEMO_TRANSACTIONS_BY_CASE: Record<string, TransResponse> = {
  "CASE-2026-0742": {
    total_transactions: 8,
    total_amount: 1875000,
    top_senders: [
      { account_id: "O-1101", total_amount: 920000, count: 4 },
      { account_id: "A-0182", total_amount: 610000, count: 2 },
      { account_id: "P-2041", total_amount: 345000, count: 2 },
    ],
    flows: [
      { source: "O-1101", target: "A-0182", count: 3, total_amount: 720000 },
      { source: "O-1101", target: "P-2041", count: 1, total_amount: 200000 },
      { source: "A-0182", target: "P-2041", count: 2, total_amount: 610000 },
      { source: "P-2041", target: "O-1101", count: 2, total_amount: 345000 },
    ],
  },
  "CASE-2026-0631": {
    total_transactions: 5,
    total_amount: 965000,
    top_senders: [
      { account_id: "A-4200", total_amount: 540000, count: 2 },
      { account_id: "A-0182", total_amount: 275000, count: 2 },
      { account_id: "N-4821", total_amount: 150000, count: 1 },
    ],
    flows: [
      { source: "A-4200", target: "A-0182", count: 2, total_amount: 540000 },
      { source: "A-0182", target: "N-4821", count: 2, total_amount: 275000 },
      { source: "N-4821", target: "A-4200", count: 1, total_amount: 150000 },
    ],
  },
};

export function TransactionsPage() {
  const { backend, cases, caseKey, setCaseKey } = useCaseSelection();
  const displayCases = cases.length ? cases : DEMO_CASES;
  const activeCaseKey = caseKey || DEMO_CASES[0].case_number;
  const [data, setData] = useState<TransResponse>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend !== "backend") {
      setData(DEMO_TRANSACTIONS_BY_CASE[activeCaseKey] ?? OFFLINE_TRANSACTIONS);
      setError(null);
      return;
    }
    if (!caseKey) return;
    apiCaseTransactions(caseKey)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, [backend, caseKey, activeCaseKey]);

  return (
    <HudPage
      title="TRANSACTION ANALYSIS"
      subtitle={backend === "backend" ? "Derived from persisted transfer edges" : "Financial flows and suspicious transfers"}
      rightMeta={<><div>{data.total_transactions} TX</div><div>{backend === "backend" ? "LIVE" : "OFFLINE DEMO"}</div></>}
    >
      <div className="hud-explorer-layout">
        <HudCard label="Case" title="Investigation selector" className="hud-explorer-search">
          <select className="control hud-search" value={caseKey || displayCases[0].case_number} onChange={(e) => setCaseKey(e.target.value)}>
            {displayCases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
          </select>
          {error && <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div>}
        </HudCard>
        <HudCard label="Volume" title="Aggregates" className="hud-explorer-grid">
          <HoloList items={[
            { label: "Total transactions", value: data.total_transactions.toLocaleString() },
            { label: "Total amount (INR)", value: `₹${data.total_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}` },
            { label: "Active flows", value: data.flows.length.toLocaleString() },
          ]} />
        </HudCard>
      </div>
      {data.top_senders.length > 0 && (
        <HudCard label="Concentration" title="Top senders">
          <div className="hud-search-hints">
            {data.top_senders.slice(0, 8).map((s) => (
              <span key={s.account_id} className="glass-strip">
                {s.account_id} · ₹{s.total_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })} · {s.count} tx
              </span>
            ))}
          </div>
        </HudCard>
      )}
      {data.flows.length > 0 && (
        <HudCard label="Transfers" title="Sender → receiver">
          <div className="table" style={{ maxHeight: 320, overflowY: "auto" }}>
            {data.flows.map((f) => (
              <div key={`${f.source}-${f.target}`} className="entity entity-tight">
                <div>
                  <div><b>{f.source}</b> → <b>{f.target}</b></div>
                  <div className="meta">{f.count} transfers · ₹{f.total_amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                </div>
              </div>
            ))}
          </div>
        </HudCard>
      )}
    </HudPage>
  );
}
