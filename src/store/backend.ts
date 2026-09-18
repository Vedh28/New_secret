/**
 * Backend connection + graph state (Phase 7).
 *
 * Manages whether the app is talking to the live FastAPI backend or falling back
 * to synthetic mock data. The frozen UI always has data either way, so a demo
 * never looks broken even when the backend is not running.
 */
import { create } from "zustand";
import {
  apiGetNetwork,
  getAccessToken,
  setAccessToken,
  type GraphResponse,
} from "../services/api";
import { prototypeGraph } from "../data/prototypeCase";

export type BackendMode = "checking" | "backend" | "mock";
const EMPTY_GRAPH: GraphResponse = prototypeGraph;

function usableGraph(network: GraphResponse | null | undefined, fallback: GraphResponse): GraphResponse {
  if (!Array.isArray(network?.nodes) || !Array.isArray(network?.edges)) return fallback;
  const nodes = network.nodes
    .filter((node) => node && typeof node.id === "string")
    .map((node) => ({ ...node, properties: node.properties ?? {} }));
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = network.edges.filter((edge) => (
    edge && typeof edge.id === "string" && nodeIds.has(edge.source) && nodeIds.has(edge.target)
  ));
  return nodes.length || edges.length ? { nodes, edges } : fallback;
}

interface BackendState {
  mode: BackendMode;
  connected: boolean;
  graph: GraphResponse;
  lastError: string | null;

  connect: () => Promise<BackendMode>;
  refreshGraph: () => Promise<void>;
  isBackend: () => boolean;
  setGraph: (graph: GraphResponse) => void;
}

export const useBackendStore = create<BackendState>((set, get) => ({
  mode: "checking",
  connected: false,
  graph: EMPTY_GRAPH,
  lastError: null,

  isBackend: () => get().mode === "backend",

  connect: async () => {
    set({ mode: "checking", lastError: null });
    if (!getAccessToken()) {
      set({ mode: "mock", connected: false, graph: EMPTY_GRAPH, lastError: "Not authenticated" });
      return "mock";
    }
    try {
      const network = await apiGetNetwork({ limit: 500 });
      const graph = usableGraph(network, get().graph);
      set({ graph, mode: "backend", connected: true, lastError: null });
      return "backend";
    } catch (err) {
      setAccessToken(null);
      set({
        mode: "mock",
        connected: false,
        graph: EMPTY_GRAPH,
        lastError: err instanceof Error ? err.message : "Backend unavailable",
      });
      return "mock";
    }
  },

  refreshGraph: async () => {
    if (get().mode !== "backend") return;
    try {
      const network = await apiGetNetwork({ limit: 500 });
      const graph = usableGraph(network, get().graph);
      if (graph !== get().graph) {
        set({ graph, lastError: null });
      } else {
        set({ lastError: null });
      }
    } catch (err) {
      // Do not drop the UI to mock just because one refresh failed.
      set({ lastError: err instanceof Error ? err.message : "Refresh failed" });
    }
  },

  setGraph: (graph) => set({ graph }),
}));
