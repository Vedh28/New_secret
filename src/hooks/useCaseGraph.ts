import { useEffect, useState } from "react";
import { useBackendStore } from "../store/backend";
import { apiCaseGraph, type GraphResponse } from "../services/api";
import { prototypeGraph } from "../data/prototypeCase";

/**
 * Case-scoped network graph (P0-2).
 *
 * Every case page must render ONLY the selected case's persisted entities and
 * relationships — never the global projection or another case's snapshot.
 * Falls back to the synthetic prototype graph only when the app is explicitly
 * in offline mode.
 */
export function useCaseGraph(caseKey: string, refreshKey?: number) {
  const backend = useBackendStore((s) => s.mode);
  const [graph, setGraph] = useState<GraphResponse>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backend === "backend" && caseKey) {
      setLoading(true);
      apiCaseGraph(caseKey)
        .then((data) => {
          setGraph({
            nodes: Array.isArray(data?.nodes) ? data.nodes : [],
            edges: Array.isArray(data?.edges) ? data.edges : [],
          });
          setError(null);
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Failed to load case graph");
          setGraph({ nodes: [], edges: [] });
        })
        .finally(() => setLoading(false));
    } else if (backend !== "backend") {
      // Explicit offline/demo mode -> synthetic prototype graph.
      setGraph(prototypeGraph);
      setError(null);
    } else {
      setGraph({ nodes: [], edges: [] });
    }
  }, [backend, caseKey, refreshKey]);

  return { graph, loading, error, offline: backend !== "backend" };
}