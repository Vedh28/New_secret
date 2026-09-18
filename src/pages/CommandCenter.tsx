import { useEffect } from "react";
import { InvestigationMap } from "../components/InvestigationMap";
import { MapControls } from "../components/InvestigationPanel";
import { TopPriorityPanel } from "../components/TopPriorityPanel";
import { useAppStore } from "../store";
import { useBackendStore } from "../store/backend";
import { useMapStore } from "../store/mapStore";
import { useCaseSelection } from "../services/useCaseSelection";
import { apiIntegritySummary } from "../services/api";
import { useIntegritySummary } from "../hooks/useIntegritySummary";

/**
 * Command Center — executive investigative intelligence view.
 *
 * Answers: what cases are active, which entities matter, what changed recently,
 * what anomalies/potential links exist, what evidence is missing, and what to
 * investigate next. All values come from the case intelligence engine (live or
 * deterministic offline) — nothing is hardcoded.
 */
export function CommandCenter() {
  const backend = useBackendStore((s) => s.mode);
  useEffect(() => {
    if (backend === "checking") return;
    void useMapStore.getState().load(backend);
  }, [backend]);

  return (
    <div className="page command-center">
      <div className="app-background-globe" aria-hidden="false">
        <InvestigationMap />
      </div>
      <TopPriorityPanel />
      <IntegrityChip />
      <div className="command-map-controls">
        <MapControls />
      </div>
    </div>
  );
}

function IntegrityChip() {
  const { caseKey, backend } = useCaseSelection();
  const { summary } = useIntegritySummary(caseKey, backend === "backend");
  const setSection = useAppStore((state) => state.setSection);

  if (backend !== "backend") {
    return (
      <button type="button" className="command-integrity-chip" onClick={() => setSection("integrity")} aria-label="Open Evidence Integrity ledger">
        <div className="hud-label">EVIDENCE INTEGRITY</div>
        <span className="integrity-status-pill status-warn">OFFLINE DEMO</span>
        <span className="meta">Synthetic demo data — not a live chain</span>
      </button>
    );
  }
  return (
    <button type="button" className="command-integrity-chip" onClick={() => setSection("integrity")} aria-label="Open Evidence Integrity ledger">
      <div className="hud-label">EVIDENCE INTEGRITY</div>
      {summary ? (
        <>
          <span className={`integrity-status-pill ${summary.chain_status === "VALID" ? "status-ok" : "status-warn"}`}>CHAIN {summary.chain_status}</span>
          <span className="command-integrity-metrics">
            <b>{summary.evidence_registered}</b> SOURCES
            <b>{summary.evidence_verified}</b> VERIFIED
            <b>{summary.mismatches}</b> ALERTS
          </span>
        </>
      ) : (
        <span className="meta">Loading integrity…</span>
      )}
      <span className="meta">OPEN EVIDENCE LEDGER →</span>
    </button>
  );
}
