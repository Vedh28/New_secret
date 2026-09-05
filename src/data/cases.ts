/**
 * Offline synthetic investigation dataset (demo mode).
 *
 * Every geographic fact here comes from existing repository data — no invented
 * coordinates or relationships:
 * - Location names/coordinates mirror the canonical demo corpus records
 *   (`demoCorpus.ts`) and the Locations page offline dataset.
 * - The old globe's INCIDENTS coordinates are migrated into proper case
 *   locations (per the Investigation Map migration rule).
 * - Entity ties come from the existing mock graph (`graphMock.ts`).
 *
 * Backend mode resolves to the exact same `CaseMarker` contract via the map
 * store, so the map always renders one source of truth.
 */
import type { CaseLocation, CaseMarker, LocationEvent } from "../types";

type LocSpec = {
  id: string;
  name: string;
  lat: number;
  lon: number;
  type: CaseLocation["type"];
  importance: number;
  entityIds: string[];
};

function loc(l: LocSpec): CaseLocation {
  return {
    id: l.id,
    caseId: "",
    name: l.name,
    latitude: l.lat,
    longitude: l.lon,
    type: l.type,
    importance: l.importance,
    timestamp: "",
    entityIds: l.entityIds,
    eventIds: [],
    observationCount: 0,
    sourceCount: 0,
  };
}

type CaseEventSpec = Omit<LocationEvent, "caseId" | "locationId" | "id"> & { locationId?: string; id?: string };

function buildCase(
  spec: {
    caseId: string;
    title: string;
    priority: string;
    status: string;
    locations: CaseLocation[];
    events: CaseEventSpec[];
  },
): CaseMarker {
  const locations = spec.locations.map((l) => ({ ...l, caseId: spec.caseId }));
  const events: LocationEvent[] = spec.events.map((e, i) => ({
    ...e,
    id: `${spec.caseId}-EVT-${String(i + 1).padStart(2, "0")}`,
    caseId: spec.caseId,
    locationId: e.locationId ?? locations[0]?.id ?? "",
  })).filter((e) => e.locationId);
  const byLoc = new Map<string, number>();
  const byLocSrc = new Map<string, Set<string>>();
  events.forEach((e) => {
    byLoc.set(e.locationId, (byLoc.get(e.locationId) ?? 0) + 1);
    e.sourceIds.forEach((s) => {
      if (!byLocSrc.has(e.locationId)) byLocSrc.set(e.locationId, new Set());
      byLocSrc.get(e.locationId)!.add(s);
    });
  });
  const withMeta = locations.map((l) => ({
    ...l,
    observationCount: byLoc.get(l.id) ?? 0,
    sourceCount: byLocSrc.get(l.id)?.size ?? 0,
    eventIds: events.filter((e) => e.locationId === l.id).map((e) => e.id),
    timestamp: events.filter((e) => e.locationId === l.id)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
      .map((e) => e.timestamp)[0] ?? "",
  }));
  const lastActivity = events
    .map((e) => e.timestamp)
    .sort()
    .slice(-1)[0] ?? "";
  const entityIds = [...new Set(withMeta.flatMap((l) => l.entityIds))];
  const locationIds = withMeta.map((l) => l.id);
  const eventIds = events.map((e) => e.id);
  return {
    caseId: spec.caseId,
    title: spec.title,
    priority: spec.priority,
    status: spec.status,
    locationIds,
    entityIds,
    eventIds,
    locations: withMeta,
    events,
    lastActivity,
  };
}

const C001 = buildCase({
  caseId: "CASE-001",
  title: "Operation Orion Traders",
  priority: "HIGH",
  status: "OPEN",
  locations: [
    loc({ id: "C001-L01", name: "Kandivali West", lat: 19.075, lon: 72.85, type: "safehouse", importance: 0.95, entityIds: ["N-4821", "P-2041", "V-2048", "L-3007"] }),
    loc({ id: "C001-L02", name: "Malad Industrial", lat: 19.186, lon: 72.849, type: "warehouse", importance: 0.9, entityIds: ["N-4821", "V-2048"] }),
    loc({ id: "C001-L03", name: "Andheri Marol", lat: 19.12, lon: 72.866, type: "contact", importance: 0.62, entityIds: ["N-7712"] }),
    loc({ id: "C001-L04", name: "BKC", lat: 19.066, lon: 72.866, type: "transfer", importance: 0.7, entityIds: ["N-2210", "A-4200"] }),
    loc({ id: "C001-L05", name: "Goregaon East", lat: 19.165, lon: 72.859, type: "contact", importance: 0.58, entityIds: ["N-9044", "P-7712"] }),
    loc({ id: "C001-L06", name: "Dadar", lat: 19.018, lon: 72.845, type: "transit", importance: 0.5, entityIds: ["N-3377"] }),
  ],
  events: [
    { id: "C001-E01", timestamp: "2026-08-14T09:00", type: "SIGHTING", entityIds: ["N-4821"], description: "Phone N-4821 observed at Kandivali West.", sourceIds: ["LOC"] },
    { id: "C001-E02", timestamp: "2026-08-14T09:25", type: "SIGHTING", entityIds: ["N-9044"], description: "Phone N-9044 observed at Goregaon East.", sourceIds: ["LOC"] },
    { id: "C001-E03", timestamp: "2026-08-14T11:50", type: "SURVEILLANCE", entityIds: ["N-4821"], description: "Suspect observed entering warehouse; phone in the 4821-series detected nearby.", sourceIds: ["SURV-01"] },
    { id: "C001-E04", timestamp: "2026-08-14T12:00", type: "SIGHTING", entityIds: ["N-4821"], description: "Phone N-4821 observed at Malad Industrial.", sourceIds: ["LOC"] },
    { id: "C001-E05", timestamp: "2026-08-14T12:30", type: "SIGHTING", entityIds: ["N-7712"], description: "Phone N-7712 observed at Andheri Marol.", sourceIds: ["LOC"] },
    { id: "C001-E06", timestamp: "2026-08-14T13:45", type: "SIGHTING", entityIds: ["N-2210"], description: "Phone N-2210 observed at BKC.", sourceIds: ["LOC"] },
    { id: "C001-E07", timestamp: "2026-08-14T14:20", type: "MOVEMENT", entityIds: ["V-2048"], description: "Vehicle V-2048 departed Malad Industrial towards Kandivali West.", sourceIds: ["SURV-02"] },
    { id: "C001-E08", timestamp: "2026-08-15T08:30", type: "SIGHTING", entityIds: ["N-4821"], description: "Phone N-4821 observed again at Kandivali West.", sourceIds: ["LOC"] },
    { id: "C001-E09", timestamp: "2026-08-15T09:05", type: "SIGHTING", entityIds: ["N-3377"], description: "Phone N-3377 observed at Dadar.", sourceIds: ["LOC"] },
    { id: "C001-E10", timestamp: "2026-08-15T10:15", type: "HANDOVER", entityIds: [], description: "Handover between two unknown persons; exchanged container seals.", sourceIds: ["SURV-03"] },
  ].map((e) => ({
    ...e,
    locationId: e.description.includes("Kandivali") ? "C001-L01"
      : e.description.includes("Malad") ? "C001-L02"
      : e.description.includes("Andheri") ? "C001-L03"
      : e.description.includes("BKC") ? "C001-L04"
      : e.description.includes("Goregaon") ? "C001-L05"
      : e.description.includes("Dadar") ? "C001-L06"
      : "C001-L01",
  })),
});

const C002 = buildCase({
  caseId: "CASE-002",
  title: "Vesper Transport Ring",
  priority: "MEDIUM",
  status: "OPEN",
  locations: [
    loc({ id: "C002-L01", name: "Borivali", lat: 19.23, lon: 72.856, type: "transit", importance: 0.55, entityIds: ["O-2033"] }),
    loc({ id: "C002-L02", name: "Dock 4", lat: 19.11, lon: 72.87, type: "transfer", importance: 0.85, entityIds: ["N-9044", "V-2048", "L-4002"] }),
    loc({ id: "C002-L03", name: "Andheri Spur", lat: 19.119, lon: 72.846, type: "contact", importance: 0.5, entityIds: ["P-7712"] }),
    loc({ id: "C002-L04", name: "Bandra", lat: 19.059, lon: 72.829, type: "transit", importance: 0.45, entityIds: ["P-7712", "N-9044"] }),
    loc({ id: "C002-L05", name: "South Mumbai", lat: 18.939, lon: 72.835, type: "safehouse", importance: 0.72, entityIds: ["V-1191"] }),
  ],
  events: [
    { id: "C002-E01", timestamp: "2026-08-14T10:12", type: "SIGHTING", entityIds: ["V-2048"], description: "Vehicle V-2048 tracked at Dock 4.", sourceIds: ["LOC"] },
    { id: "C002-E02", timestamp: "2026-08-14T16:30", type: "TRANSFER", entityIds: ["N-9044"], description: "Call handoff logged in the Borivali corridor.", sourceIds: ["CDR"] },
    { id: "C002-E03", timestamp: "2026-08-15T07:40", type: "MOVEMENT", entityIds: ["V-1191"], description: "Vehicle V-1191 observed near South Mumbai.", sourceIds: ["SURV-02"] },
  ].map((e) => ({
    ...e,
    locationId: e.description.includes("Dock") ? "C002-L02"
      : e.description.includes("Borivali") ? "C002-L01"
      : e.description.includes("South Mumbai") ? "C002-L05"
      : "C002-L04",
  })),
});

const C003 = buildCase({
  caseId: "CASE-003",
  title: "Mirage Cell Signals",
  priority: "LOW",
  status: "OPEN",
  locations: [
    loc({ id: "C003-L01", name: "Sector 17", lat: 19.0755, lon: 72.8492, type: "safehouse", importance: 0.88, entityIds: ["N-4821", "P-2041", "L-3007"] }),
    loc({ id: "C003-L02", name: "Dadar", lat: 19.018, lon: 72.845, type: "transit", importance: 0.45, entityIds: ["N-3377"] }),
    loc({ id: "C003-L03", name: "South Mumbai", lat: 18.939, lon: 72.835, type: "contact", importance: 0.4, entityIds: ["V-1191", "A-0182"] }),
  ],
  events: [
    { id: "C003-E01", timestamp: "2026-08-13T18:22", type: "SIGHTING", entityIds: ["N-4821"], description: "Signals from Sector 17 cell observed.", sourceIds: ["CDR"] },
    { id: "C003-E02", timestamp: "2026-08-14T19:05", type: "TRANSFER", entityIds: ["A-0182"], description: "Transaction pattern tied to South Mumbai.", sourceIds: ["TX"] },
  ].map((e) => ({
    ...e,
    locationId: e.description.includes("Sector") ? "C003-L01"
      : e.description.includes("South Mumbai") ? "C003-L03"
      : "C003-L02",
  })),
});

export const offlineCaseMarkers: CaseMarker[] = [C001, C002, C003];

export const casePriorityRank: Record<string, number> = { HIGH: 3, MEDIUM: 2, LOW: 1 };