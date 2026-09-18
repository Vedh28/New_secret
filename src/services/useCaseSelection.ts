import { useCallback, useEffect, useState } from "react";
import { useBackendStore } from "../store/backend";
import { useMapStore } from "../store/mapStore";
import { apiListCases, type CaseRead } from "./api";
import { prototypeCases } from "../data/prototypeCase";

/**
 * Shared "select a case" state for analysis pages.
 *
 * The selected case is stored in the global map store (`selectedCaseId`), so a
 * case chosen on any page (Command Center, Intake, Network, ...) propagates
 * everywhere else. Falls back to prototype/synthetic cases when the backend is
 * offline.
 */
export function useCaseSelection() {
  const backend = useBackendStore((s) => s.mode);
  const selectedCaseId = useMapStore((s) => s.selectedCaseId);
  const [cases, setCases] = useState<CaseRead[]>([]);

  const caseKey = selectedCaseId ?? "";
  const setCaseKey = useCallback((key: string) => {
    useMapStore.getState().selectCase(key || null);
  }, []);

  const reload = useCallback(async () => {
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