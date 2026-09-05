/**
 * Investigation Map overlay panels for the Command Center.
 *
 * Reuses existing HUD styling (`.hud-card`, `.pill`, `.glass-strip`) so no new
 * visual language is introduced. All values derive from `useMapStore` — no
 * analytic numbers are invented here.
 */
import { useMemo } from "react";
import { RotateCcw, Map as MapIcon, Crosshair } from "lucide-react";
import { useMapStore } from "../store/mapStore";
import { useAppStore } from "../store";

function Toggle({ label, value, onToggle }: { label: string; value: boolean; onToggle: () => void }) {
  return (
    <button
      className={`map-toggle ${value ? "is-on" : ""}`}
      onClick={onToggle}
      aria-pressed={value}
      title={label}
    >
      {label}
    </button>
  );
}

/** Time-window chips derived from real event timestamps (shared across Command Center + Timeline). */
export function MapWindowChips() {
  const store = useMapStore;
  const markers = useMapStore((s) => s.markers);
  const range = useMapStore((s) => s.range);
  const days = useMemo(() => {
    const dates = new Set<string>();
    markers.forEach((m) => m.events.forEach((e) => {
      const d = e.timestamp.slice(0, 10);
      if (d) dates.add(d);
    }));
    return [...dates].sort();
  }, [markers]);
  if (days.length < 1) return null;
  return (
    <div className="map-controls-row">
      <span className="map-control-label">WINDOW</span>
      <button
        className={`map-toggle ${range === null ? "is-on" : ""}`}
        onClick={() => store.getState().setTimeRange(null)}
      >
        ALL
      </button>
      {days.map((d) => {
        const active = range?.start.slice(0, 10) === d;
        return (
          <button
            key={d}
            className={`map-toggle ${active ? "is-on" : ""}`}
            onClick={() => store.getState().setTimeRange({ start: `${d}T00:00`, end: `${d}T23:59` })}
          >
            {d.slice(8)}
          </button>
        );
      })}
    </div>
  );
}

export function MapControls() {
  const store = useMapStore;
  const showCases = useMapStore((s) => s.showCases);
  const showLocations = useMapStore((s) => s.showLocations);
  const showRoutes = useMapStore((s) => s.showRoutes);
  const showLabels = useMapStore((s) => s.showLabels);

  return (
    <div className="map-controls">
      <div className="map-controls-row">
        <button className="pill map-control-btn" onClick={() => store.getState().requestCamera("reset")} title="Reset camera">
          <RotateCcw size={12} /> RESET
        </button>
        <button className="pill map-control-btn" onClick={() => store.getState().requestCamera("fit-all")} title="Fit all cases">
          <MapIcon size={12} /> FIT ALL
        </button>
        <button
          className="pill map-control-btn"
          disabled={!store.getState().selectedCaseId}
          onClick={() => {
            const id = store.getState().selectedCaseId;
            if (id) store.getState().requestCamera("fit-case", id);
          }}
          title="Fit selected case"
        >
          <Crosshair size={12} /> FIT CASE
        </button>
      </div>
      <div className="map-controls-row">
        <Toggle label="CASES" value={showCases} onToggle={() => store.getState().toggleFlag("showCases")} />
        <Toggle label="LOCATIONS" value={showLocations} onToggle={() => store.getState().toggleFlag("showLocations")} />
        <Toggle label="ROUTES" value={showRoutes} onToggle={() => store.getState().toggleFlag("showRoutes")} />
        <Toggle label="LABELS" value={showLabels} onToggle={() => store.getState().toggleFlag("showLabels")} />
      </div>
      <MapWindowChips />
    </div>
  );
}

export function InvestigationIntelPanel() {
  const markers = useMapStore((s) => s.markers);
  const selectedCaseId = useMapStore((s) => s.selectedCaseId);
  const selectedLocationId = useMapStore((s) => s.selectedLocationId);
  const setSection = useAppStore((s) => s.setSection);

  const selCase = useMemo(() => markers.find((m) => m.caseId === selectedCaseId) ?? null, [markers, selectedCaseId]);
  const selLoc = useMemo(() => markers.flatMap((m) => m.locations).find((l) => l.id === selectedLocationId) ?? null, [markers, selectedLocationId]);
  const locEvents = useMemo(() => {
    if (!selLoc) return [];
    return selCase?.events.filter((e) => e.locationId === selLoc.id) ?? [];
  }, [selLoc, selCase]);

  if (!selLoc && !selCase) return null;
  const viewEntity = () => {
    if (selLoc?.entityIds[0]) useMapStore.getState().selectEntity(selLoc.entityIds[0]);
    setSection("network");
  };
  const viewTimeline = () => {
    setSection("timeline");
  };

  return (
    <div className="hud-card map-intel-panel">
      <span className="hud-corner hud-corner-tl" />
      <span className="hud-corner hud-corner-tr" />
      <span className="hud-corner hud-corner-bl" />
      <span className="hud-corner hud-corner-br" />
      <div className="hud-label">{selLoc ? "LOCATION INTELLIGENCE" : "CASE INTELLIGENCE"}</div>
      {selLoc ? (
        <>
          <div className="map-intel-title">{selLoc.name}</div>
          <div className="map-intel-sub">{selLoc.caseId}</div>
          <div className="map-intel-grid">
            <div><span>OBSERVATIONS</span><b>{selLoc.observationCount ?? locEvents.length}</b></div>
            <div><span>ENTITIES</span><b>{selLoc.entityIds.length}</b></div>
            <div><span>EVENTS</span><b>{locEvents.length}</b></div>
            <div><span>SOURCES</span><b>{selLoc.sourceCount ?? new Set(locEvents.flatMap((e) => e.sourceIds)).size}</b></div>
            <div><span>LAST ACTIVITY</span><b>{(selLoc.timestamp || selCase?.lastActivity) ? new Date(selLoc.timestamp || selCase!.lastActivity).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</b></div>
            <div><span>PRIMARY ENTITY</span><b>{selLoc.entityIds[0] ?? "—"}</b></div>
          </div>
          <div className="map-intel-actions">
            <button className="pill" onClick={viewTimeline}>VIEW TIMELINE</button>
            <button className="pill" onClick={viewEntity}>VIEW NETWORK</button>
            {locEvents.length > 0 && (
              <details className="map-intel-evidence">
                <summary>VIEW EVIDENCE ({locEvents.length})</summary>
                <div className="map-intel-evidence-list">
                  {locEvents.slice(0, 6).map((e) => (
                    <div key={e.id} className="map-intel-evidence-item">
                      <span className="tag">{e.type} · {new Date(e.timestamp).toLocaleDateString([], { day: "2-digit", month: "short" })} {new Date(e.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                      <div className="meta">{e.description}</div>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </>
      ) : selCase ? (
        <>
          <div className="map-intel-title">{selCase.caseId}</div>
          <div className="map-intel-sub">{selCase.title}</div>
          <div className="map-intel-grid">
            <div><span>PRIORITY</span><b className="map-intel-priority">{selCase.priority}</b></div>
            <div><span>STATUS</span><b>{selCase.status}</b></div>
            <div><span>LOCATIONS</span><b>{selCase.locations.length}</b></div>
            <div><span>ENTITIES</span><b>{selCase.entityIds.length}</b></div>
            <div><span>EVENTS</span><b>{selCase.events.length}</b></div>
            <div><span>LAST ACTIVITY</span><b>{selCase.lastActivity ? new Date(selCase.lastActivity).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</b></div>
          </div>
          <div className="map-intel-actions">
            <button className="pill" onClick={() => useMapStore.getState().requestCamera("fit-case", selCase.caseId)}>FIT CASE</button>
            <button className="pill" onClick={() => useMapStore.getState().clearSelection()}>DESELECT</button>
          </div>
        </>
      ) : null}
    </div>
  );
}