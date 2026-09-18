/**
 * Investigation Map global state.
 *
 * Single unified source of geographic truth for the Command Center map, Network
 * Intelligence and Timeline. Holds the `CaseMarker[]` contract (backend or
 * offline — same shape), selection state shared across views, view toggles and
 * the timeline time-window. No markup-specific state lives here; the map
 * component only subscribes and renders.
 */
import { create } from "zustand";
import type { CaseLocation, CaseMarker } from "../types";
import { apiListCases, apiCaseLocations } from "../services/api";
import { offlineCaseMarkers } from "../data/cases";

export type MapSource = "backend" | "mock";

export type CameraRequest =
  | { kind: "fit-case"; caseId: string; nonce: number }
  | { kind: "fit-location"; locationId: string; nonce: number }
  | { kind: "fit-point"; lat: number; lon: number; zoomDist?: number; nonce: number }
  | { kind: "fit-all"; nonce: number }
  | { kind: "reset"; nonce: number };

type MapFlags = {
  showCases: boolean;
  showLocations: boolean;
  showRoutes: boolean;
  showLabels: boolean;
};

type TimeRange = { start: string; end: string } | null;

interface MapState extends MapFlags {
  markers: CaseMarker[];
  source: MapSource;
  loading: boolean;
  error: string | null;

  selectedCaseId: string | null;
  selectedLocationId: string | null;
  selectedEntityId: string | null;

  range: TimeRange;
  lastLoadedAt: string | null;

  cameraRequest: CameraRequest | null;

  load: (source: MapSource) => Promise<void>;
  selectCase: (caseId: string | null) => void;
  selectLocation: (locationId: string | null) => void;
  selectEntity: (entityId: string | null) => void;
  setTimeRange: (range: TimeRange) => void;
  toggleFlag: (key: keyof MapFlags) => void;
  requestCamera: (kind: CameraRequest["kind"], id?: string) => void;
  flyToGeo: (lat: number, lon: number, zoomDist?: number) => void;
  clearSelection: () => void;

  locationById: (id: string) => CaseLocation | null;
  locationsForEntity: (entityId: string) => CaseLocation[];
  dataTimeline: () => { start: string; end: string } | null;
}

function dedupe(items: string[]): string[] {
  return [...new Set(items)];
}

async function loadBackend(): Promise<CaseMarker[]> {
  const list = await apiListCases({ limit: 100 });
  const markers: CaseMarker[] = [];
  for (const c of list.items) {
    try {
      const locRes = await apiCaseLocations(c.case_number);
      const visits = (locRes.visits ?? []).filter((v) => v.latitude && v.longitude);
      const locations: CaseLocation[] = visits.map((v, i) => ({
        id: `${c.case_number}:${v.location}:${i}`,
        caseId: c.case_number,
        name: v.location,
        latitude: parseFloat(v.latitude!),
        longitude: parseFloat(v.longitude!),
        type: "unknown",
        importance: Math.min(1, (v.observations ?? 1) / 8),
        timestamp: "",
        entityIds: v.linked_entity_id ? [v.linked_entity_id] : v.entity_id ? [v.entity_id] : [],
        entityNames: v.linked_entity_name ? [v.linked_entity_name] : [],
        eventIds: [],
        observationCount: v.observations,
        sourceCount: 1,
      }));
      markers.push({
        caseId: c.case_number,
        title: c.title,
        priority: c.priority,
        status: c.status,
        locationIds: locations.map((l) => l.id),
        entityIds: dedupe(locations.flatMap((l) => l.entityIds)),
        eventIds: [],
        locations,
        events: [],
        lastActivity: c.updated_at,
      });
    } catch {
      // Case without geographic data — keep it out of the map rather than
      // inventing coordinates.
    }
  }
  return markers;
}

export const useMapStore = create<MapState>((set, get) => ({
  markers: offlineCaseMarkers,
  source: "mock",
  loading: false,
  error: null,

  selectedCaseId: null,
  selectedLocationId: null,
  selectedEntityId: null,

  range: null,
  lastLoadedAt: null,

  showCases: true,
  showLocations: true,
  showRoutes: true,
  showLabels: true,
  cameraRequest: null,

  load: async (source) => {
    set({ loading: source === "backend", source, error: null });
    try {
      const markers = source === "backend" ? await loadBackend() : offlineCaseMarkers;
      const selectedCaseId = get().selectedCaseId;
      const caseStillExists = markers.some((m) => m.caseId === selectedCaseId);
      set({
        markers,
        source,
        loading: false,
        lastLoadedAt: new Date().toISOString(),
        ...(selectedCaseId && !caseStillExists ? { selectedCaseId: null, selectedLocationId: null } : {}),
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : "Map data load failed",
        markers: offlineCaseMarkers,
        source: "mock",
      });
    }
  },

  selectCase: (caseId) => set({
    selectedCaseId: caseId,
    ...(caseId ? { selectedLocationId: null } : {}),
  }),

  selectLocation: (locationId) => {
    const selectedLocationId = locationId;
    const selectedCaseId = locationId
      ? (get().markers.find((m) => m.locations.some((l) => l.id === locationId))?.caseId ?? get().selectedCaseId)
      : get().selectedCaseId;
    set({ selectedLocationId, selectedCaseId });
  },

  selectEntity: (entityId) => set({ selectedEntityId: entityId }),

  setTimeRange: (range) => set({ range }),

  toggleFlag: (key) => set((s) => ({ [key]: !s[key] }) as Partial<MapState>),

  requestCamera: (kind, id) => {
    const nonce = (get().cameraRequest?.nonce ?? 0) + 1;
    let req: CameraRequest;
    if (kind === "fit-case") {
      req = { kind: "fit-case", caseId: id ?? "", nonce };
    } else if (kind === "fit-location") {
      req = { kind: "fit-location", locationId: id ?? "", nonce };
    } else if (kind === "fit-all") {
      req = { kind: "fit-all", nonce };
    } else {
      req = { kind: "reset", nonce };
    }
    set({ cameraRequest: req });
  },

  flyToGeo: (lat, lon, zoomDist = 32) => {
    const nonce = (get().cameraRequest?.nonce ?? 0) + 1;
    set({ cameraRequest: { kind: "fit-point", lat, lon, zoomDist, nonce } });
  },

  clearSelection: () => set({ selectedCaseId: null, selectedLocationId: null }),

  locationById: (id) => {
    if (!id) return null;
    for (const m of get().markers) {
      const found = m.locations.find((l) => l.id === id);
      if (found) return found;
    }
    return null;
  },

  locationsForEntity: (entityId) => {
    if (!entityId) return [];
    return get().markers.flatMap((m) => m.locations.filter((l) => l.entityIds.includes(entityId)));
  },

  dataTimeline: () => {
    const stamps = get().markers.flatMap((m) => m.events.map((e) => e.timestamp))
      .filter((t) => !!t)
      .sort();
    if (!stamps.length) return null;
    return { start: stamps[0], end: stamps[stamps.length - 1] };
  },
}));
