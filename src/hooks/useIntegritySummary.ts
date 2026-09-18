import { useEffect, useState } from "react";
import { apiIntegritySummary, type IntegritySummary } from "../services/api";

/**
 * Case-scoped integrity ledger summary. Live mode only: offline demo never
 * presents a fake chain. Cache-lite (single fetch per caseKey change) so the
 * Command Center + integrity pages don't hammer the backend.
 */
export function useIntegritySummary(caseKey: string, enabled: boolean) {
  const [summary, setSummary] = useState<IntegritySummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !caseKey) {
      setSummary(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    apiIntegritySummary(caseKey)
      .then((data) => {
        if (!cancelled) { setSummary(data); setError(null); }
      })
      .catch((err) => {
        if (!cancelled) { setError(err instanceof Error ? err.message : "Integrity unavailable"); setSummary(null); }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [caseKey, enabled]);

  return { summary, loading, error };
}