/**
 * Investigation Map overlay panels for the Command Center.
 *
 * Reuses existing HUD styling (`.hud-card`, `.pill`, `.glass-strip`) so no new
 * visual language is introduced. All values derive from `useMapStore` — no
 * analytic numbers are invented here.
 */
import { useMemo, useState } from "react";
import { RotateCcw, Map as MapIcon, Crosshair, Search, MapPin, X } from "lucide-react";
import { useMapStore } from "../store/mapStore";
import { useAppStore } from "../store";
import citiesData from "../data/map/cities.json";
import transitData from "../data/map/transit.json";
import districtsData from "../data/map/maharashtra-districts.json";
import indiaStatesData from "../data/map/india-states.json";

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

/** Pre-indexed places for global search & zoom */
type SearchItem = {
  name: string;
  type: "city" | "district" | "station" | "state" | "case" | "location";
  label: string;
  lat: number;
  lon: number;
  zoomDist: number;
};

export function MapControls() {
  const store = useMapStore;
  const markers = useMapStore((s) => s.markers);
  const showCases = useMapStore((s) => s.showCases);
  const showLocations = useMapStore((s) => s.showLocations);
  const showRoutes = useMapStore((s) => s.showRoutes);
  const showLabels = useMapStore((s) => s.showLabels);

  const [searchQuery, setSearchQuery] = useState("");
  const [showResults, setShowResults] = useState(false);

  // Search catalog index across all geographic entities
  const searchIndex = useMemo<SearchItem[]>(() => {
    const items: SearchItem[] = [];

    // Cities
    (citiesData as { cities: { name: string; lat: number; lon: number; major: boolean }[] }).cities.forEach((c) => {
      items.push({
        name: c.name,
        type: "city",
        label: `${c.name} · City`,
        lat: c.lat,
        lon: c.lon,
        zoomDist: c.major ? 38 : 30,
      });
    });

    // Maharashtra Districts
    (districtsData as { districts: { name: string; polygons: number[][][][] }[] }).districts.forEach((d) => {
      let latSum = 0, lonSum = 0, count = 0;
      d.polygons.forEach((poly) => {
        poly.forEach((ring) => {
          ring.forEach(([lon, lat]) => {
            latSum += lat;
            lonSum += lon;
            count++;
          });
        });
      });
      if (count > 0) {
        items.push({
          name: d.name,
          type: "district",
          label: `${d.name} · District (MH)`,
          lat: latSum / count,
          lon: lonSum / count,
          zoomDist: 34,
        });
      }
    });

    // Transit Stations
    (transitData as { stations: { code: string; name: string; city: string; lat: number; lon: number }[] }).stations.forEach((st) => {
      items.push({
        name: st.name,
        type: "station",
        label: `${st.name} [${st.code}] · Rail Station`,
        lat: st.lat,
        lon: st.lon,
        zoomDist: 26,
      });
    });

    // Indian States
    (indiaStatesData as { states: { name: string; polygons: number[][][][] }[] }).states.forEach((s) => {
      let latSum = 0, lonSum = 0, count = 0;
      s.polygons.forEach((poly) => {
        poly.forEach((ring) => {
          ring.forEach(([lon, lat]) => {
            latSum += lat;
            lonSum += lon;
            count++;
          });
        });
      });
      if (count > 0) {
        items.push({
          name: s.name,
          type: "state",
          label: `${s.name} · State`,
          lat: latSum / count,
          lon: lonSum / count,
          zoomDist: 90,
        });
      }
    });

    // Case locations
    markers.forEach((m) => {
      items.push({
        name: m.title,
        type: "case",
        label: `${m.caseId}: ${m.title}`,
        lat: m.locations.reduce((s, l) => s + l.latitude, 0) / Math.max(1, m.locations.length),
        lon: m.locations.reduce((s, l) => s + l.longitude, 0) / Math.max(1, m.locations.length),
        zoomDist: 40,
      });
      m.locations.forEach((loc) => {
        items.push({
          name: loc.name,
          type: "location",
          label: `${loc.name} · Incident Point`,
          lat: loc.latitude,
          lon: loc.longitude,
          zoomDist: 24,
        });
      });
    });

    return items;
  }, [markers]);

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];
    return searchIndex.filter((item) =>
      item.name.toLowerCase().includes(q) || item.label.toLowerCase().includes(q)
    ).slice(0, 8);
  }, [searchQuery, searchIndex]);

  const handleSelectPlace = (item: SearchItem) => {
    store.getState().flyToGeo(item.lat, item.lon, item.zoomDist);
    setSearchQuery(item.name);
    setShowResults(false);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (filtered.length > 0) {
      handleSelectPlace(filtered[0]);
    }
  };

  return (
    <div className="map-controls">
      {/* Search and Zoom Input */}
      <div className="map-search-bar-wrap">
        <form onSubmit={handleSearchSubmit} className="map-search-form">
          <Search size={14} className="map-search-icon" />
          <input
            type="text"
            className="map-search-input"
            placeholder="Search place, city, district, station, state..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setShowResults(true);
            }}
            onFocus={() => setShowResults(true)}
            aria-label="Search and zoom to place"
          />
          {searchQuery && (
            <button
              type="button"
              className="map-search-clear"
              onClick={() => {
                setSearchQuery("");
                setShowResults(false);
              }}
            >
              <X size={12} />
            </button>
          )}
        </form>

        {showResults && filtered.length > 0 && (
          <div className="map-search-results">
            {filtered.map((item, idx) => (
              <button
                key={`${item.type}-${item.name}-${idx}`}
                className="map-search-item"
                onClick={() => handleSelectPlace(item)}
              >
                <MapPin size={12} className={`map-search-type-icon ${item.type}`} />
                <span className="map-search-item-label">{item.label}</span>
                <span className="map-search-item-type">{item.type}</span>
              </button>
            ))}
          </div>
        )}
      </div>

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