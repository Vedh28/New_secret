import { useEffect, useRef, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { apiCaseLocations, type LocationsResponse } from "../services/api";
import { useCaseSelection } from "../services/useCaseSelection";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";

const EMPTY: LocationsResponse = { locations: [], visits: [] };

/**
 * Synthetic offline location dataset (demo mode). Coherent with the existing
 * mock entities/graph (N-, V-, L- identifiers) and carries synthetic
 * coordinates so the offline page still shows real-looking observations.
 */
const OFFLINE_LOCATIONS: LocationsResponse = {
  locations: [
    { name: "Sector 17", observations: 4 },
    { name: "Dock 4", observations: 3 },
    { name: "Kandivali West", observations: 2 },
    { name: "Malad Industrial", observations: 2 },
    { name: "BKC", observations: 1 },
  ],
  visits: [
    { location: "Sector 17", entity_id: "N-4821", latitude: "19.0750", longitude: "72.8500", observations: 2 },
    { location: "Sector 17", entity_id: "P-2041", latitude: "19.0755", longitude: "72.8492", observations: 2 },
    { location: "Dock 4", entity_id: "N-9044", latitude: "19.1100", longitude: "72.8700", observations: 2 },
    { location: "Dock 4", entity_id: "V-2048", latitude: "19.1108", longitude: "72.8691", observations: 1 },
    { location: "Kandivali West", entity_id: "N-4821", latitude: "19.0750", longitude: "72.8500", observations: 2 },
    { location: "Malad Industrial", entity_id: "V-2048", latitude: "19.1860", longitude: "72.8490", observations: 2 },
    { location: "BKC", entity_id: "A-4200", latitude: "19.0660", longitude: "72.8660", observations: 1 },
  ],
};

type LocationVisit = LocationsResponse["visits"][number];

function OpenStreetMapSurface({ visits }: { visits: LocationVisit[] }) {
  const mapRef = useRef<HTMLDivElement>(null);
  const coordinates = visits.map((visit) => ({
    visit,
    lat: Number.parseFloat(visit.latitude ?? ""),
    lng: Number.parseFloat(visit.longitude ?? ""),
  })).filter((entry) => Number.isFinite(entry.lat) && Number.isFinite(entry.lng));

  useEffect(() => {
    if (!mapRef.current || !coordinates.length) return;

    const renderMap = () => {
      const leaflet = (window as Window & { L?: any }).L;
      if (!leaflet || !mapRef.current) return;
      const map = leaflet.map(mapRef.current, { zoomControl: false, attributionControl: true });
      leaflet.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
      coordinates.forEach(({ visit, lat, lng }) => {
        leaflet.circleMarker([lat, lng], { radius: 8, color: "#07101f", weight: 2, fillColor: "#62d3ff", fillOpacity: 1 })
          .addTo(map)
          .bindTooltip(`${visit.location} · ${visit.entity_id}`, { permanent: true, direction: "top", className: "hud-map-tooltip" });
      });
      map.fitBounds(leaflet.latLngBounds(coordinates.map(({ lat, lng }) => [lat, lng])), { padding: [42, 42] });
      setTimeout(() => map.invalidateSize(), 0);
    };

    const existingScript = document.querySelector<HTMLScriptElement>('script[data-leaflet="true"]');
    if (!document.querySelector('link[data-leaflet-style="true"]')) {
      const style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
      style.dataset.leafletStyle = "true";
      document.head.appendChild(style);
    }
    if ((window as Window & { L?: any }).L) {
      renderMap();
      return;
    }
    if (existingScript) {
      existingScript.addEventListener("load", renderMap, { once: true });
      return () => existingScript.removeEventListener("load", renderMap);
    }
    const script = document.createElement("script");
    script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    script.async = true;
    script.defer = true;
    script.dataset.leaflet = "true";
    script.addEventListener("load", renderMap, { once: true });
    document.head.appendChild(script);
    return () => script.removeEventListener("load", renderMap);
  }, [visits]);

  if (!coordinates.length) {
    return <div className="meta hud-location-empty">No coordinates available for this case.</div>;
  }
  return <div ref={mapRef} className="hud-location-map-canvas" aria-label="OpenStreetMap of observed locations" />;
}

export function LocationsPage() {
  const { backend, cases, caseKey, setCaseKey } = useCaseSelection();
  const [data, setData] = useState<LocationsResponse>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const { intel: caseIntel } = useCaseIntelligence(caseKey);

  useEffect(() => {
    if (backend !== "backend") {
      // Offline / demo mode: use the synthetic location dataset.
      setData(OFFLINE_LOCATIONS);
      setError(null);
      return;
    }
    if (!caseKey) {
      setData(EMPTY);
      return;
    }
    apiCaseLocations(caseKey)
      .then(setData)
      .catch((err) => { setData(OFFLINE_LOCATIONS); setError(err instanceof Error ? err.message : "Failed to load"); });
  }, [backend, caseKey]);

  const hotspots = [...data.locations].sort((a, b) => b.observations - a.observations).slice(0, 6);
  const demoTags = backend === "backend";
  return (
    <HudPage
      title="LOCATION INTELLIGENCE"
      subtitle={demoTags ? "Location entities from ingested records" : "Synthetic geospatial demo dataset"}
      rightMeta={<><div>{data.visits.length} OBSERVATIONS</div>{demoTags ? <div>LIVE</div> : <div>DEMO</div>}</>}
    >
      {demoTags && (
        <HudCard label="Case" title="Investigation selector">
          <select className="control hud-search" value={caseKey} onChange={(e) => setCaseKey(e.target.value)}>
            {cases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
          </select>
          {error && <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{error}</div>}
        </HudCard>
      )}

      <div className="hud-location-layout" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <HudCard label="Spatial surface" title="Observed Locations" className="hud-location-map">
          <div className="hud-location-surface">
            <OpenStreetMapSurface visits={data.visits} />
            <div className="hud-location-summary">
              <span>Mumbai region</span>
              <strong>{hotspots.length} hotspots · {data.visits.length} visits</strong>
            </div>
          </div>
        </HudCard>
        <HudCard label="Entity sightings" title="Who was observed where">
          <HoloList
            items={data.visits.slice(0, 12).map((v) => ({
              label: v.location,
              value: `${v.entity_id}${v.latitude && v.longitude ? ` · ${v.latitude}, ${v.longitude}` : ""} · ${v.observations}`,
            }))}
          />
        </HudCard>
        {caseIntel && (
          <HudCard label="Spatial anomalies" title="Unusual location activity">
            <div className="stack">
              {(caseIntel.anomalies ?? []).filter((a) => a.kind === "LOCATION").slice(0, 3).map((a) => (
                <div key={a.entity_id} className="alert high">
                  <div><div className="tag">{a.entity_id}</div><div>{a.explanation}</div></div>
                </div>
              ))}
              {!caseIntel.anomalies?.some((a) => a.kind === "LOCATION") && (
                <div className="meta">No location anomaly signals flagged for this case.</div>
              )}
            </div>
          </HudCard>
        )}
        <HudCard label="Activity hotspots" title="Location Clusters">
          <div className="stack">
            {hotspots.map((h) => (
              <div key={h.name} className="entity entity-tight">
                <div>
                  <div>{h.name}</div>
                  <div className="meta">{h.observations} observations</div>
                </div>
                <div className="risk">{h.observations}</div>
              </div>
            ))}
            {!hotspots.length && <div className="meta">No location entities yet for this case.</div>}
          </div>
        </HudCard>
      </div>
    </HudPage>
  );
}
