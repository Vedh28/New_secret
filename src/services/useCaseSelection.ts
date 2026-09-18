import { useCallback, useEffect, useRef, useState } from "react";
import { useBackendStore } from "../store/backend";
import { useMapStore } from "../store/mapStore";
import { apiListCases, apiRecordAudit, type CaseRead } from "./api";
import { prototypeCases } from "../data/prototypeCase";

/**
 * Shared "select a case" state for analysis pages.
 *
 * The selected case is stored in the global map store (`selectedCaseId`), so a
 * case chosen on any page (Command Center, Intake, Network, ...) propagates
 * everywhere else. Falls back to prototype/synthetic cases ONLY when the app
 * is explicitly in offline mode.
 */
export function useCaseSelection() {
  const backend = useBackendStore((s) => s.mode);
  const selectedCaseId = useMapStore((s) => s.selectedCaseId);
  const [cases, setCases] = useState<CaseRead[]>([]);
  const previousCaseRef = useRef<string | null>(null);

  const caseKey = selectedCaseId ?? "";
  const setCaseKey = useCallback((key: string) => {
    useMapStore.getState().selectCase(key || null);
  }, []);

  // Record an audit entry when the investigator actively opens (switches to) a
  // live case. Best-effort + silent; skips the initial mount to avoid spam.
  useEffect(() => {
    if (backend !== "backend" || !caseKey) {
      previousCaseRef.current = caseKey || null;
      return;
    }
    const previous = previousCaseRef.current;
    previousCaseRef.current = caseKey;
    if (previous !== null && previous !== caseKey) {
      apiRecordAudit({ action: "case_opened", object_type: "case", object_id: caseKey, result: { mode: "live" } })
        .catch(() => undefined);
    }
  }, [backend, caseKey]);

  const reload = useCallback(() => {
    const current = useMapStore.getState().selectedCaseId;
    if (backend !== "backend") {
      setCases(prototypeCases.map((item, index) => ({
        id: index + 1,
        case_number: item.caseId,
        title: item.title,
        description: item.title,
        status: item.status,
        priority: item.priority,
        created_at: item.lastActivity,
        updated_at: item.lastActivity,
      })));
      useMapStore.getState().selectCase(current || prototypeCases[0]?.caseId || null);
      return;
    }
    apiListCases({ limit: 100 })
      .then((res) => {
        setCases(res.items);
        const stillValid = current && res.items.some((c) => c.case_number === current);
        useMapStore.getState().selectCase(stillValid ? current : (res.items[0]?.case_number ?? null));
      })
      .catch(() => setCases([]));
  }, [backend]);

  useEffect(() => {
    reload();
  }, [reload]);

  return { backend, cases, caseKey, setCaseKey, reload };
}