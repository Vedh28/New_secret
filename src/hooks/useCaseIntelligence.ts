import { useEffect, useState } from "react";
import { useBackendStore } from "../store/backend";
import { apiCaseIntelligence, type CaseIntelligence } from "../services/api";
import { prototypeIntelligence, prototypeIntelligenceByCase } from "../data/prototypeCase";

/**
 * Fetch case intelligence for a caseKey. In OFFLINE mode it returns the
 * deterministic synthetic snapshot mirroring the backend engines. In LIVE mode
 * it fetches ONLY the selected case — hardcoded demo values never leak into a
 * live case.
 */
export function useCaseIntelligence(caseKey: string, refreshKey?: number) {
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
  }, [backend, caseKey, refreshKey]);

  return { intel, loading, error, offline: backend !== "backend", offlineIntel: prototypeIntelligenceByCase[caseKey] ?? prototypeIntelligence };
}
