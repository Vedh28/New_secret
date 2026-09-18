import { useCallback, useEffect, useState } from "react";
import { useBackendStore } from "../store/backend";
import { useMapStore } from "../store/mapStore";
import { apiListCases, type CaseRead } from "./api";
import { prototypeCases } from "../data/prototypeCase";

/**
 * Shared "select a case" state for analysis pages. Falls back to null when the
 * backend is offline so pages can render their demo/synthetic view.
 */
export function useCaseSelection() {
  const backend = useBackendStore((s) => s.mode);
  const [cases, setCases] = useState<CaseRead[]>([]);
  const [caseKey, setCaseKey] = useState<string>("");

  const reload = useCallback(() => {
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
      setCaseKey((prev) => prev || prototypeCases[0]?.caseId || "");
      return;
    }
    apiListCases({ limit: 100 })
      .then((res) => {
        setCases(res.items);
        setCaseKey((prev) => prev || res.items[0]?.case_number || "");
      })
      .catch(() => setCases([]));
  }, [backend]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Keep the investigation map in sync: when any page settles on a case, the
  // map highlights that case's locations on return to the Command Center.
  useEffect(() => {
    if (caseKey) useMapStore.getState().selectCase(caseKey);
  }, [caseKey]);

  return { backend, cases, caseKey, setCaseKey, reload };
}
