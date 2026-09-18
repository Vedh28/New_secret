import { useEffect } from "react";
import { InvestigationMap } from "../components/InvestigationMap";
import { MapControls } from "../components/InvestigationPanel";
import { TopPriorityPanel } from "../components/TopPriorityPanel";
import { useBackendStore } from "../store/backend";
import { useMapStore } from "../store/mapStore";

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
      <div className="command-map-controls">
        <MapControls />
      </div>
    </div>
  );
}
