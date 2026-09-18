/**
 * InvestigationMap — MapLibre intelligence map.
 *
 * OpenFreeMap supplies the MapLibre-compatible OSM vector style and building
 * source without a vendor token. Case/location data stays in useMapStore so
 * the command page controls and intelligence panels keep their contract.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import * as THREE from "three";
import type { Map as MapLibreMap, MapMouseEvent, IControl, MapGeoJSONFeature, CustomRenderMethodInput } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useMapStore } from "../store/mapStore";
import type { CaseMarker } from "../types";
import { prototypeEntities } from "../data/prototypeCase";

const INDIA_CENTER: [number, number] = [78.9629, 20.5937];
const INDIA_BOUNDS: [[number, number], [number, number]] = [[67, 6.5], [98, 37.2]];
const OPENFREEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const OPENFREEMAP_PLANET = "https://tiles.openfreemap.org/planet";
const BUILDING_HEIGHT: maplibregl.ExpressionSpecification = [
  "coalesce",
  ["to-number", ["get", "render_height"]],
  ["to-number", ["get", "height"]],
  ["*", ["to-number", ["get", "building:levels"]], 3],
  0,
];
const BUILDING_BASE: maplibregl.ExpressionSpecification = [
  "coalesce",
  ["to-number", ["get", "render_min_height"]],
  ["to-number", ["get", "min_height"]],
  0,
];

const MAP_COLORS = {
  background: "#050816",
  land: "#0a1024",
  landDetail: "#111a38",
  water: "#0e2f5c",
  waterway: "#3f73ff",
  roadMajor: "#1e5aa7",
  roadMinor: "#143b65",
  roadService: "#0d2945",
  roadCasing: "#050b14",
  boundary: "#3f73ff",
  boundaryAccent: "#62d3ff",
  building: "#131d3d",
  buildingBright: "#20406e",
  text: "#f4f6ff",
  textAccent: "#62d3ff",
  textHalo: "#050816",
};
function curvedRoute(points: number[][]): number[][] {
  if (points.length < 2) return points;
  const coordinates: number[][] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const distance = Math.hypot(dx, dy);
    const bulge = Math.min(3.2, Math.max(0.18, distance * 0.075));
    const normalX = distance ? -dy / distance : 0;
    const normalY = distance ? dx / distance : 0;
    const control: [number, number] = [
      (start[0] + end[0]) / 2 + normalX * bulge,
      (start[1] + end[1]) / 2 + normalY * bulge,
    ];
    for (let step = 0; step <= 18; step += 1) {
      if (index > 0 && step === 0) continue;
      const t = step / 18;
      const inverse = 1 - t;
      coordinates.push([
        inverse * inverse * start[0] + 2 * inverse * t * control[0] + t * t * end[0],
        inverse * inverse * start[1] + 2 * inverse * t * control[1] + t * t * end[1],
      ]);
    }
  }
  return coordinates;
}
const BUILDING_COLOR: maplibregl.ExpressionSpecification = [
  "interpolate", ["linear"], BUILDING_HEIGHT,
  0, "#131d3d", 30, "#183052", 90, "#1d4566", 220, "#2a6f98", 420, "#62a8d4",
];
const BUILDING_OPACITY: maplibregl.ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"],
  13, 0.2, 14, 0.34, 15, 0.5, 17, 0.68, 20, 0.78,
];

type MapHover = { id: string; x: number; y: number } | null;

function priorityColor(priority: string): string {
  if (priority === "HIGH") return "#ffbd55";
  if (priority === "MEDIUM") return "#62d3ff";
  return "#5a8fa8";
}

function routeColor(priority: string): string {
  if (priority === "HIGH") return "#762532";
  if (priority === "MEDIUM") return "#5f202d";
  return "#421923";
}

function centerOf(marker: CaseMarker): [number, number] | null {
  if (!marker.locations.length) return null;
  const primary = marker.locations.reduce((best, location) => (
    location.importance > best.importance ? location : best
  ));
  return [primary.longitude, primary.latitude];
}

function primaryLocation(marker: CaseMarker): CaseMarker["locations"][number] | null {
  return marker.locations.reduce<CaseMarker["locations"][number] | null>(
    (best, location) => (!best || location.importance > best.importance ? location : best),
    null,
  );
}

function featureCollection(features: GeoJSON.Feature[]): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features };
}

function mapPoint(feature: GeoJSON.Feature, map: MapLibreMap, event: MapMouseEvent): MapHover {
  const id = String(feature.properties?.id ?? "");
  const rect = map.getContainer().getBoundingClientRect();
  const point = map.project(event.lngLat);
  return { id, x: rect.left + point.x, y: rect.top + point.y };
}

function eventFeatures(event: MapMouseEvent): MapGeoJSONFeature[] {
  // The installed maplibre type omits .features on MapMouseEvent although the
  // runtime populates it for sourced layers; read it defensively.
  return (event as unknown as { features?: MapGeoJSONFeature[] }).features ?? [];
}

class PitchControl implements IControl {
  private container?: HTMLDivElement;

  onAdd(map: MapLibreMap): HTMLElement {
    this.container = document.createElement("div");
    this.container.className = "maplibregl-ctrl maplibregl-ctrl-group maplibre-pitch-control";
    const button = document.createElement("button");
    button.type = "button";
    button.title = "Toggle 3D pitch";
    button.setAttribute("aria-label", "Toggle 3D pitch");
    button.textContent = "3D";
    button.addEventListener("click", () => {
      const nextPitch = map.getPitch() > 20 ? 0 : 58;
      map.easeTo({ pitch: nextPitch, duration: 650 });
    });
    this.container.appendChild(button);
    return this.container;
  }

  onRemove(): void {
    this.container?.remove();
    this.container = undefined;
  }
}

class OrbitControl implements IControl {
  private container?: HTMLDivElement;
  private button?: HTMLButtonElement;

  constructor(private readonly onToggle: () => void) {}

  onAdd(map: MapLibreMap): HTMLElement {
    this.container = document.createElement("div");
    this.container.className = "maplibregl-ctrl maplibregl-ctrl-group maplibre-orbit-control";
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.title = "Toggle cinematic orbit around the selected location";
    this.button.setAttribute("aria-label", "Toggle cinematic orbit");
    this.button.textContent = "ORBIT";
    this.button.addEventListener("click", this.onToggle);
    this.container.appendChild(this.button);
    return this.container;
  }

  setActive(active: boolean) {
    this.button?.classList.toggle("is-active", active);
    if (this.button) this.button.textContent = active ? "STOP" : "ORBIT";
  }

  onRemove(): void {
    this.button?.removeEventListener("click", this.onToggle);
    this.container?.remove();
    this.button = undefined;
    this.container = undefined;
  }
}

function addMapLayers(map: MapLibreMap) {
  map.setLight({
    anchor: "viewport",
    color: "#b8dcff",
    intensity: 0.38,
    position: [1.25, 210, 55],
  });

  if (!map.getSource("openfreemap")) map.addSource("openfreemap", { type: "vector", url: OPENFREEMAP_PLANET });

  if (!map.getLayer("secret-building-footprints")) {
    map.addLayer({
      id: "secret-building-footprints",
      source: "openfreemap",
      "source-layer": "building",
      type: "fill",
      minzoom: 14,
      filter: ["all", ["!=", ["get", "hide_3d"], true], [">", BUILDING_HEIGHT, 0]],
      paint: {
        "fill-color": "#0b2035",
        "fill-opacity": ["interpolate", ["linear"], ["zoom"], 14, 0.18, 16, 0.36, 20, 0.56],
        "fill-outline-color": "#1d4b78",
      },
    });
  }

  if (!map.getLayer("secret-3d-buildings")) {
    const labelLayer = map.getStyle().layers?.find((layer) => layer.type === "symbol" && Boolean(layer.layout?.["text-field"]));
    map.addLayer({
      id: "secret-3d-buildings",
      source: "openfreemap",
      "source-layer": "building",
      type: "fill-extrusion",
      minzoom: 14,
      filter: ["all", ["!=", ["get", "hide_3d"], true], [">", BUILDING_HEIGHT, 0]],
      paint: {
        "fill-extrusion-color": BUILDING_COLOR,
        "fill-extrusion-height": ["interpolate", ["linear"], ["zoom"], 14, 0, 15, BUILDING_HEIGHT],
        "fill-extrusion-base": BUILDING_BASE,
        "fill-extrusion-opacity": BUILDING_OPACITY,
        "fill-extrusion-vertical-gradient": true,
      },
    }, labelLayer?.id);
  }

  if (!map.getLayer("secret-building-edges")) {
    const labelLayer = map.getStyle().layers?.find((layer) => layer.type === "symbol" && Boolean(layer.layout?.["text-field"]));
    map.addLayer({
      id: "secret-building-edges",
      source: "openfreemap",
      "source-layer": "building",
      type: "line",
      minzoom: 15,
      filter: ["all", ["!=", ["get", "hide_3d"], true], [">", BUILDING_HEIGHT, 0]],
      paint: {
        "line-color": "#2a6f98",
        "line-width": ["interpolate", ["linear"], ["zoom"], 15, 0.2, 17, 0.55, 20, 1],
        "line-opacity": ["interpolate", ["linear"], ["zoom"], 15, 0.16, 17, 0.42, 20, 0.7],
      },
    }, labelLayer?.id);
  }

  if (!map.getSource("secret-data")) map.addSource("secret-data", { type: "geojson", data: featureCollection([]) });
  if (!map.getLayer("secret-route-glass")) {
    map.addLayer({
      id: "secret-route-glass", type: "line", source: "secret-data", filter: ["==", ["get", "kind"], "route"],
      layout: { visibility: "visible", "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#d94a5f", "line-width": 12, "line-opacity": 0.06, "line-blur": 6 },
    });
  }
  if (!map.getLayer("secret-route-frost")) {
    map.addLayer({
      id: "secret-route-frost", type: "line", source: "secret-data", filter: ["==", ["get", "kind"], "route"],
      layout: { visibility: "visible", "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "routeColor"], "line-width": 7, "line-opacity": 0.16, "line-blur": 2.2 },
    });
  }
  if (!map.getLayer("secret-routes")) {
    map.addLayer({
      id: "secret-routes", type: "line", source: "secret-data", filter: ["==", ["get", "kind"], "route"],
      layout: { visibility: "visible", "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "routeColor"], "line-width": 1.8, "line-opacity": 0.82 },
    });
  }
  if (!map.getLayer("secret-cases")) {
    map.addLayer({
      id: "secret-cases", type: "circle", source: "secret-data", filter: ["==", ["get", "kind"], "case"],
      paint: { "circle-radius": ["case", ["get", "selected"], 10, 7], "circle-color": ["get", "color"], "circle-stroke-color": "#e7fbff", "circle-stroke-width": 2, "circle-opacity": 0.98, "circle-blur": 0.08 },
    });
  }
  if (!map.getLayer("secret-case-halos")) {
    map.addLayer({
      id: "secret-case-halos", type: "circle", source: "secret-data", filter: ["==", ["get", "kind"], "case"],
      paint: { "circle-radius": ["case", ["get", "selected"], 22, 15], "circle-color": ["get", "color"], "circle-opacity": ["case", ["get", "selected"], 0.16, 0.08], "circle-blur": 0.86 },
    }, "secret-cases");
  }
  if (!map.getLayer("secret-case-rings")) {
    map.addLayer({
      id: "secret-case-rings", type: "circle", source: "secret-data", filter: ["==", ["get", "kind"], "case"],
      paint: {
        "circle-radius": ["case", ["get", "selected"], 17, 11],
        "circle-color": "rgba(0,0,0,0)",
        "circle-opacity": 0,
        "circle-stroke-color": ["get", "color"],
        "circle-stroke-width": ["case", ["get", "selected"], 2.2, 1.4],
        "circle-stroke-opacity": ["case", ["get", "selected"], 0.95, 0.72],
      },
    }, "secret-cases");
  }
  if (!map.getLayer("secret-case-labels")) {
    map.addLayer({
      id: "secret-case-labels", type: "symbol", source: "secret-data", filter: ["==", ["get", "kind"], "case"],
      layout: { "text-field": "", "text-size": ["interpolate", ["linear"], ["zoom"], 2, 9, 8, 10.5, 14, 12], "text-offset": [0, 2.15], "text-anchor": "top", "text-allow-overlap": true, "text-letter-spacing": 0.04 },
      paint: { "text-color": "#f4fbff", "text-halo-color": "#050b14", "text-halo-width": 2, "text-opacity": 0.98 },
    });
  }
  if (!map.getLayer("secret-locations")) {
    map.addLayer({
      id: "secret-locations", type: "circle", source: "secret-data", filter: ["==", ["get", "kind"], "location"],
      paint: { "circle-radius": ["case", ["get", "selected"], 7, 4], "circle-color": ["get", "color"], "circle-stroke-color": "#dff8ff", "circle-stroke-width": ["case", ["get", "selected"], 2, 1], "circle-opacity": 0.98 },
    });
  }
  if (!map.getLayer("secret-location-labels")) {
    map.addLayer({
      id: "secret-location-labels", type: "symbol", source: "secret-data", filter: ["==", ["get", "kind"], "location"],
      layout: { "text-field": ["get", "name"], "text-size": 10, "text-offset": [0, 1.2], "text-anchor": "top", "text-allow-overlap": false },
      paint: { "text-color": "#dff8ff", "text-halo-color": "#061326", "text-halo-width": 1.5 },
    });
  }
}

function setPaint(map: MapLibreMap, layerId: string, property: string, value: unknown) {
  if (!map.getLayer(layerId)) return;
  try {
    // The setter's typed keys lag maplibre's runtime paint properties; we pass
    // through the raw string key exactly as the provider expects.
    (map as unknown as { setPaintProperty: (id: string, p: string, v: unknown) => void }).setPaintProperty(layerId, property, value);
  } catch (error) {
    // Some provider layers omit optional paint properties; keep those layers intact.
    console.warn(`[map-style] Could not recolor ${layerId}.${property}`, error);
  }
}

function recolorMapStyle(map: MapLibreMap) {
  const layers = map.getStyle().layers ?? [];
  layers.forEach((layer) => {
    const id = layer.id.toLowerCase();
    const sourceLayer = String((layer as { "source-layer"?: string })["source-layer"] ?? "").toLowerCase();

    if (layer.type === "background") setPaint(map, layer.id, "background-color", MAP_COLORS.background);
    // Keep the operational map vector-only; provider raster/hillshade layers
    // can otherwise wash out the dark intelligence palette after globe reloads.
    if (layer.type === "raster") setPaint(map, layer.id, "raster-opacity", 0);
    if (layer.type === "hillshade") setPaint(map, layer.id, "hillshade-opacity", 0);

    if (layer.type === "fill" && (sourceLayer === "park" || sourceLayer === "landuse" || sourceLayer === "landcover")) {
      const isGrass = id === "landcover_grass";
      const isWood = id === "landcover_wood";
      const isWetland = id === "landcover_wetland";
      const isOpenLand = id === "landcover_sand" || id === "landuse_pitch" || id === "landuse_track";
      const isCivicLand = id === "landuse_cemetery" || id === "landuse_hospital" || id === "landuse_school";
      const color = sourceLayer === "park" ? "#0d2038" : isGrass ? "#0b2239" : isWood ? "#0b2036" : isWetland ? "#091a2e" : isOpenLand ? "#10233b" : isCivicLand ? "#122844" : MAP_COLORS.landDetail;
      setPaint(map, layer.id, "fill-color", color);
      setPaint(map, layer.id, "fill-opacity", sourceLayer === "park" ? 0.5 : isWetland ? 0.2 : isGrass || isWood ? 0.34 : 0.62);
      setPaint(map, layer.id, "fill-outline-color", isWetland ? "#15324e" : "#142d49");
      setPaint(map, layer.id, "fill-pattern", null);
    }
    if (layer.type === "line" && sourceLayer === "park") {
      setPaint(map, layer.id, "line-color", "#153653");
      setPaint(map, layer.id, "line-opacity", 0.3);
    }
    if (layer.type === "line" && sourceLayer === "landcover") {
      setPaint(map, layer.id, "line-color", "#153653");
      setPaint(map, layer.id, "line-opacity", 0.3);
    }
    if (layer.type === "fill" && sourceLayer === "water") {
      setPaint(map, layer.id, "fill-color", MAP_COLORS.water);
      setPaint(map, layer.id, "fill-opacity", 0.94);
    }

    if (layer.type === "fill" && sourceLayer === "aeroway") {
      setPaint(map, layer.id, "fill-color", "#10243a");
      setPaint(map, layer.id, "fill-opacity", 0.48);
    }

    if (layer.type === "line" && sourceLayer === "aeroway") {
      setPaint(map, layer.id, "line-color", "#1a466d");
      setPaint(map, layer.id, "line-opacity", 0.52);
    }

    if (layer.type === "line" && sourceLayer === "waterway") {
      setPaint(map, layer.id, "line-color", "#24558a");
      setPaint(map, layer.id, "line-opacity", 0.72);
    }
    if (layer.type === "line" && sourceLayer === "boundary") {
      setPaint(map, layer.id, "line-color", id.includes("disputed") ? MAP_COLORS.boundaryAccent : MAP_COLORS.boundary);
      setPaint(map, layer.id, "line-opacity", id.includes("disputed") ? 0.55 : 0.72);
    }

    if (layer.type === "line" && sourceLayer === "transportation") {
      const isCasing = id.includes("casing");
      const isRail = id.includes("rail") || id.includes("transit");
      const isMajor = id.includes("motorway") || id.includes("trunk") || id.includes("primary") || id.includes("secondary");
      const isService = id.includes("service") || id.includes("track") || id.includes("path") || id.includes("pedestrian");
      const color = isRail ? MAP_COLORS.boundaryAccent : isCasing ? MAP_COLORS.roadCasing : isMajor ? MAP_COLORS.roadMajor : isService ? MAP_COLORS.roadService : MAP_COLORS.roadMinor;
      setPaint(map, layer.id, "line-color", color);
      setPaint(map, layer.id, "line-opacity", isCasing ? 0.9 : isRail ? 0.82 : 0.78);
    }

    if (layer.type === "fill" && sourceLayer === "building") {
      const isFootprintLayer = id === "secret-building-footprints";
      setPaint(map, layer.id, "fill-color", isFootprintLayer ? "#0b2035" : MAP_COLORS.building);
      setPaint(map, layer.id, "fill-opacity", isFootprintLayer ? ["interpolate", ["linear"], ["zoom"], 14, 0.18, 16, 0.36, 20, 0.56] : 0.78);
      setPaint(map, layer.id, "fill-outline-color", "#1d4b78");
    }
    if (layer.type === "line" && sourceLayer === "building") {
      setPaint(map, layer.id, "line-color", "#2a6f98");
      setPaint(map, layer.id, "line-opacity", ["interpolate", ["linear"], ["zoom"], 15, 0.16, 17, 0.42, 20, 0.7]);
    }
    if (layer.type === "fill-extrusion" && sourceLayer === "building") {
      setPaint(map, layer.id, "fill-extrusion-color", BUILDING_COLOR);
      setPaint(map, layer.id, "fill-extrusion-opacity", BUILDING_OPACITY);
      setPaint(map, layer.id, "fill-extrusion-vertical-gradient", true);
    }

    if (layer.type === "symbol") {
      if (layer.layout?.["icon-image"]) setPaint(map, layer.id, "icon-opacity", 0);
      setPaint(map, layer.id, "text-color", sourceLayer === "poi" ? MAP_COLORS.textAccent : MAP_COLORS.text);
      setPaint(map, layer.id, "text-halo-color", MAP_COLORS.textHalo);
      setPaint(map, layer.id, "text-halo-width", 1.25);
      setPaint(map, layer.id, "icon-color", MAP_COLORS.textAccent);
      setPaint(map, layer.id, "icon-halo-color", MAP_COLORS.textHalo);
    }
  });

  [
    ["highway-name-path", 15],
    ["highway-name-minor", 14],
    ["poi_r20", 13],
    ["poi_r7", 15],
    ["poi_r1", 16],
  ].forEach(([layerId, minZoom]) => {
    if (map.getLayer(String(layerId))) map.setLayerZoomRange(String(layerId), Number(minZoom), 24);
  });
}

function buildData(markers: CaseMarker[], showCases: boolean, showLocations: boolean, showRoutes: boolean, selectedCaseId: string | null, selectedLocationId: string | null): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  markers.forEach((marker) => {
    const color = priorityColor(marker.priority);
    const isSelected = marker.caseId === selectedCaseId;
    // Keep the map uncluttered: case markers are the entry points, while the
    // selected case reveals only its own locations and route.
    const revealDetails = Boolean(selectedCaseId) && isSelected;
    const center = centerOf(marker);
    if (showCases && center) features.push({ type: "Feature", properties: { kind: "case", id: marker.caseId, color, priority: marker.priority, selected: isSelected, title: marker.title }, geometry: { type: "Point", coordinates: center } });
    if (showRoutes && revealDetails && center) {
      marker.locations.forEach((location) => {
        const point: [number, number] = [location.longitude, location.latitude];
        if (point[0] === center[0] && point[1] === center[1]) return;
        features.push({
          type: "Feature",
          properties: { kind: "route", color, routeColor: routeColor(marker.priority), from: marker.caseId, to: location.id },
          geometry: { type: "LineString", coordinates: [center, point] },
        });
      });
    }
    if (showLocations && revealDetails) marker.locations.forEach((location) => features.push({ type: "Feature", properties: { kind: "location", id: location.id, caseId: marker.caseId, color, selected: location.id === selectedLocationId, name: location.name }, geometry: { type: "Point", coordinates: [location.longitude, location.latitude] } }));
  });
  return featureCollection(features);
}

function fitAll(map: MapLibreMap, markers: CaseMarker[]) {
  const locations = markers.flatMap((marker) => marker.locations);
  const cameraPadding = { top: 120, bottom: 120, left: 120, right: 120 };
  if (!locations.length) { map.fitBounds(INDIA_BOUNDS, { padding: cameraPadding, pitch: 58, bearing: -14, duration: 1200, essential: true }); return; }
  const bounds = new maplibregl.LngLatBounds();
  locations.forEach((location) => bounds.extend([location.longitude, location.latitude]));
  map.fitBounds(bounds, { padding: cameraPadding, maxZoom: 13, pitch: 58, bearing: -14, duration: 1200, essential: true });
}

function offsetCoordinate(target: [number, number], bearing: number, distanceMeters: number): [number, number] {
  const bearingRadians = (bearing * Math.PI) / 180;
  const latitudeRadians = (target[1] * Math.PI) / 180;
  const latitude = target[1] + (Math.cos(bearingRadians) * distanceMeters) / 111320;
  const longitude = target[0] + (Math.sin(bearingRadians) * distanceMeters) / (111320 * Math.max(0.2, Math.cos(latitudeRadians)));
  return [longitude, latitude];
}

function cinematicCameraOptions(map: MapLibreMap, target: [number, number], bearing: number, distanceMeters: number, altitudeMeters: number) {
  const cameraPosition = offsetCoordinate(target, bearing, distanceMeters);
  return map.calculateCameraOptionsFromTo(
    new maplibregl.LngLat(cameraPosition[0], cameraPosition[1]),
    altitudeMeters,
    new maplibregl.LngLat(target[0], target[1]),
    8,
  );
}

function cinematicPitchForZoom(zoom: number): number {
  if (zoom <= 6) return 56;
  if (zoom <= 11) return 56 + ((zoom - 6) / 5) * 8;
  if (zoom <= 16) return 64 + ((zoom - 11) / 5) * 10;
  return Math.min(78, 74 + (zoom - 16) * 1.1);
}

type ThreeIntelOverlay = maplibregl.CustomLayerInterface & {
  setTarget: (target: [number, number] | null) => void;
};

function createThreeIntelOverlay(): ThreeIntelOverlay {
  const scene = new THREE.Scene();
  const group = new THREE.Group();
  scene.add(group);
  let renderer: THREE.WebGLRenderer | null = null;
  let camera: THREE.Camera | null = null;
  let mapInstance: MapLibreMap | null = null;
  let origin: maplibregl.MercatorCoordinate | null = null;
  let meterScale = 0;
  let animationStart = performance.now();

  const disposeGroup = () => {
    group.traverse((object) => {
      const mesh = object as THREE.Mesh;
      mesh.geometry?.dispose();
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(material)) material.forEach((item) => item.dispose());
      else material?.dispose();
    });
    group.clear();
  };

  const overlay: ThreeIntelOverlay = {
    id: "secret-three-intel-overlay",
    type: "custom",
    renderingMode: "3d",
    onAdd(map, gl) {
      mapInstance = map;
      renderer = new THREE.WebGLRenderer({ canvas: map.getCanvas(), context: gl, antialias: true, alpha: true });
      renderer.autoClear = false;
      renderer.setClearColor(0x000000, 0);
      camera = new THREE.Camera();
      animationStart = performance.now();
    },
    render(gl, input: CustomRenderMethodInput) {
      if (!renderer || !camera || !origin || !meterScale) return;
      const projection = new THREE.Matrix4().fromArray(input.modelViewProjectionMatrix as number[]);
      const translation = new THREE.Matrix4().makeTranslation(origin.x, origin.y, origin.z);
      const rotation = new THREE.Matrix4().makeRotationX(Math.PI / 2);
      const scale = new THREE.Matrix4().makeScale(meterScale, -meterScale, meterScale);
      camera.projectionMatrix = projection.multiply(translation).multiply(rotation).multiply(scale);

      const elapsed = (performance.now() - animationStart) / 1000;
      group.rotation.y = elapsed * 0.24;
      const pulse = 1 + Math.sin(elapsed * 2.8) * 0.08;
      group.children.forEach((child, index) => {
        if (index > 0 && child instanceof THREE.Mesh) child.scale.setScalar(index % 2 === 0 ? pulse : 1 / pulse);
      });
      renderer.resetState();
      renderer.render(scene, camera);
      mapInstance?.triggerRepaint();
    },
    setTarget(target) {
      disposeGroup();
      if (!target) {
        origin = null;
        meterScale = 0;
        return;
      }
      origin = maplibregl.MercatorCoordinate.fromLngLat(target, 0);
      meterScale = origin.meterInMercatorCoordinateUnits();
      const cyan = new THREE.MeshBasicMaterial({ color: 0x67e8f9, transparent: true, opacity: 0.78, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false });
      const blue = new THREE.MeshBasicMaterial({ color: 0x2563eb, transparent: true, opacity: 0.42, blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false });
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(1.2, 1.2, 64, 12), cyan);
      pole.position.y = 32;
      group.add(pole);
      const baseRing = new THREE.Mesh(new THREE.TorusGeometry(18, 0.8, 8, 64), blue);
      baseRing.position.y = 3;
      group.add(baseRing);
      const targetRing = new THREE.Mesh(new THREE.TorusGeometry(10, 1.1, 8, 64), cyan);
      targetRing.position.y = 70;
      group.add(targetRing);
      const beacon = new THREE.Mesh(new THREE.OctahedronGeometry(5, 1), cyan);
      beacon.position.y = 74;
      group.add(beacon);
    },
    onRemove() {
      disposeGroup();
      renderer?.dispose();
      renderer = null;
      camera = null;
      mapInstance = null;
      origin = null;
    },
  };
  return overlay;
}

export function InvestigationMap() {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const orbitFrameRef = useRef<number | null>(null);
  const orbitEnabledRef = useRef(false);
  const orbitFocusRef = useRef<[number, number] | null>(null);
  const orbitBearingRef = useRef(-14);
  const stopOrbitRef = useRef<() => void>(() => {});
  const startOrbitRef = useRef<() => void>(() => {});
  const threeOverlayRef = useRef<ThreeIntelOverlay | null>(null);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<MapHover>(null);
  const markers = useMapStore((state) => state.markers);
  const showCases = useMapStore((state) => state.showCases);
  const showLocations = useMapStore((state) => state.showLocations);
  const showRoutes = useMapStore((state) => state.showRoutes);
  const showLabels = useMapStore((state) => state.showLabels);
  const selectedCaseId = useMapStore((state) => state.selectedCaseId);
  const selectedLocationId = useMapStore((state) => state.selectedLocationId);
  const cameraRequest = useMapStore((state) => state.cameraRequest);
  const hoveredMarker = useMemo(() => hover && markers.find((marker) => marker.caseId === hover.id), [hover, markers]);
  const hoveredLocation = useMemo(() => hover && markers.flatMap((marker) => marker.locations).find((location) => location.id === hover.id), [hover, markers]);
  const hoveredEntities = useMemo(() => hoveredLocation
    ? hoveredLocation.entityIds.map((id, index) => hoveredLocation.entityNames?.[index] ?? prototypeEntities.find((entity) => entity.id === id)?.name ?? id)
    : [], [hoveredLocation]);
  const selectedMarker = useMemo(() => selectedCaseId ? markers.find((marker) => marker.caseId === selectedCaseId) : null, [markers, selectedCaseId]);

  useEffect(() => {
    if (!hostRef.current) return;
    const map = new maplibregl.Map({ container: hostRef.current, style: OPENFREEMAP_STYLE, projection: { type: "globe" }, center: INDIA_CENTER, zoom: 3, pitch: 60, bearing: -14, maxPitch: 78, maxZoom: 22, minZoom: 2, pitchWithRotate: true, dragRotate: true, canvasContextAttributes: { antialias: true } } as unknown as maplibregl.MapOptions);
    mapRef.current = map;
    const threeOverlay = createThreeIntelOverlay();
    threeOverlayRef.current = threeOverlay;
    // Use finer, more responsive zoom steps while retaining MapLibre's eased motion.
    map.scrollZoom.setWheelZoomRate(1 / 450);
    map.scrollZoom.setZoomRate(1 / 70);
    map.touchZoomRotate.setZoomRate(0.75);
    map.touchZoomRotate.enableRotation();
    const syncCinematicZoom = () => {
      if (orbitEnabledRef.current) return;
      const nextPitch = cinematicPitchForZoom(map.getZoom());
      if (Math.abs(map.getPitch() - nextPitch) > 0.2) map.setPitch(nextPitch);
    };
    map.on("zoom", syncCinematicZoom);
    map.addControl(new maplibregl.NavigationControl({ showZoom: true, showCompass: true, visualizePitch: true }), "bottom-right");
    map.addControl(new PitchControl(), "bottom-right");
    let orbitControl: OrbitControl;
    let projectionRecolorPending = false;
    const stopOrbit = () => {
      orbitEnabledRef.current = false;
      if (orbitFrameRef.current !== null) cancelAnimationFrame(orbitFrameRef.current);
      orbitFrameRef.current = null;
      orbitControl?.setActive(false);
    };
    const orbitFrame = () => {
      if (!orbitEnabledRef.current || !orbitFocusRef.current) return;
      orbitBearingRef.current += 0.035;
      const zoom = map.getZoom();
      const distance = Math.max(180, Math.min(900, 260 * Math.pow(2, 16 - zoom)));
      const altitude = Math.max(120, distance * 0.58);
      const camera = cinematicCameraOptions(map, orbitFocusRef.current, orbitBearingRef.current, distance, altitude);
      map.easeTo({ ...camera, duration: 0, essential: true });
      orbitFrameRef.current = requestAnimationFrame(orbitFrame);
    };
    const startOrbit = () => {
      orbitFocusRef.current ??= [map.getCenter().lng, map.getCenter().lat];
      orbitBearingRef.current = map.getBearing();
      orbitEnabledRef.current = true;
      orbitControl.setActive(true);
      const distance = Math.max(180, Math.min(900, 260 * Math.pow(2, 16 - map.getZoom())));
      const camera = cinematicCameraOptions(map, orbitFocusRef.current, orbitBearingRef.current, distance, Math.max(120, distance * 0.58));
      map.easeTo({ ...camera, duration: 700, essential: true });
      orbitFrameRef.current = requestAnimationFrame(orbitFrame);
    };
    const toggleOrbit = () => {
      if (orbitEnabledRef.current) stopOrbit();
      else startOrbit();
    };
    orbitControl = new OrbitControl(toggleOrbit);
    stopOrbitRef.current = stopOrbit;
    startOrbitRef.current = startOrbit;
    map.addControl(orbitControl, "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");
    const reapplyAfterProjection = () => {
      if (!projectionRecolorPending || !map.isStyleLoaded()) return;
      projectionRecolorPending = false;
      addMapLayers(map);
      recolorMapStyle(map);
      const st = useMapStore.getState();
      const ds = map.getSource("secret-data") as maplibregl.GeoJSONSource | undefined;
      ds?.setData(buildData(st.markers, st.showCases, st.showLocations, st.showRoutes, st.selectedCaseId, st.selectedLocationId));
      if (map.getLayer("secret-location-labels")) map.setLayoutProperty("secret-location-labels", "visibility", st.showLabels && st.showLocations ? "visible" : "none");
      ["secret-route-glass", "secret-route-frost", "secret-routes"].forEach((layerId) => { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", st.showRoutes ? "visible" : "none"); });
    };
    map.on("idle", reapplyAfterProjection);
    const applyStyleTheme = () => {
      if (!map.isStyleLoaded()) return;
      ["secret-global-intel-glow", "secret-global-intel-arcs"].forEach((layerId) => {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
      });
      if (map.getSource("secret-global-intel")) map.removeSource("secret-global-intel");
      // Bend the planet into a 3D globe like Google Earth, with atmospheric
      // fog/glow so the round horizon and space read clearly behind the map.
      const projection = map.getProjection();
      if (projection?.type !== "globe") {
        projectionRecolorPending = true;
        map.setProjection({ type: "globe" });
      }
      // Older MapLibre builds do not expose fog; keep the globe usable there.
      if (typeof (map as unknown as { setFog?: (f: unknown) => void }).setFog === "function") {
        (map as unknown as { setFog: (f: unknown) => void }).setFog({
          "range": [2, 9],
          "color": "#0d1838",
          "high-color": "#102a4a",
          "horizon-color": "#0b1b35",
          "space-color": "#050816",
          "star-intensity": 0.08,
        });
      }
      addMapLayers(map);
      // Globe projection triggers an async style reload that wipes GeoJSON
      // source data.  Re-inject the current marker set so case/location dots
      // survive every reload cycle.
      const st = useMapStore.getState();
      const ds = map.getSource("secret-data") as maplibregl.GeoJSONSource | undefined;
      if (ds) ds.setData(buildData(st.markers, st.showCases, st.showLocations, st.showRoutes, st.selectedCaseId, st.selectedLocationId));
      if (map.getLayer("secret-location-labels")) map.setLayoutProperty("secret-location-labels", "visibility", st.showLabels && st.showLocations ? "visible" : "none");
      ["secret-route-glass", "secret-route-frost", "secret-routes"].forEach((layerId) => { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", st.showRoutes ? "visible" : "none"); });
      recolorMapStyle(map);
      if (!map.getLayer(threeOverlay.id)) map.addLayer(threeOverlay);
      setReady(true);
      syncCinematicZoom();
    };
    const onLocationClick = (event: MapMouseEvent) => {
      const feature = eventFeatures(event)[0];
      const id = String(feature?.properties?.id ?? "");
      if (!id) return;
      const store = useMapStore.getState();
      const location = store.locationById(id);
      store.selectLocation(id); store.selectEntity(location?.entityIds[0] ?? null); store.requestCamera("fit-location", id); setHover(null);
    };
    const onCaseClick = (event: MapMouseEvent) => {
      const caseLayers = ["secret-cases", "secret-case-halos", "secret-case-labels"]
        .filter((layerId) => Boolean(map.getLayer(layerId)));
      const feature = (map.queryRenderedFeatures(event.point, { layers: caseLayers })[0] ?? eventFeatures(event)[0]) as MapGeoJSONFeature | undefined;
      const id = String(feature?.properties?.id ?? "");
      if (!id) return;
      const store = useMapStore.getState();
      store.selectCase(id);
      store.selectEntity(null);
      setHover(null);
    };
    const onMove = (event: MapMouseEvent) => {
      const feature = eventFeatures(event)[0];
      if (!feature) { setHover(null); map.getCanvas().style.cursor = "grab"; return; }
      map.getCanvas().style.cursor = "pointer"; setHover(mapPoint(feature, map, event));
    };
    const onLeave = () => { setHover(null); map.getCanvas().style.cursor = "grab"; };
    const stopOrbitOnInput = () => { if (orbitEnabledRef.current) stopOrbit(); };
    map.getCanvas().addEventListener("mousedown", stopOrbitOnInput);
    map.getCanvas().addEventListener("touchstart", stopOrbitOnInput, { passive: true });
    map.getCanvas().addEventListener("wheel", stopOrbitOnInput, { passive: true });
    map.on("load", applyStyleTheme);
    map.once("idle", applyStyleTheme);
    map.on("click", "secret-locations", onLocationClick);
    map.on("click", "secret-cases", onCaseClick);
    map.on("click", "secret-case-halos", onCaseClick);
    map.on("click", "secret-case-labels", onCaseClick);
    // Query all case presentation layers so clicks on the glow or ID label
    // trigger the same close-up camera as clicks on the core marker.
    map.on("click", onCaseClick);
    map.on("mousemove", "secret-locations", onMove);
    map.on("mousemove", "secret-cases", onMove);
    map.on("mouseleave", "secret-locations", onLeave);
    map.on("mouseleave", "secret-cases", onLeave);
    return () => {
      stopOrbit();
      stopOrbitRef.current = () => {};
      startOrbitRef.current = () => {};
      map.getCanvas().removeEventListener("mousedown", stopOrbitOnInput);
      map.getCanvas().removeEventListener("touchstart", stopOrbitOnInput);
      map.getCanvas().removeEventListener("wheel", stopOrbitOnInput);
      map.remove();
      mapRef.current = null;
      threeOverlayRef.current = null;
    };
  }, []);

  useEffect(() => {
    const location = markers.flatMap((marker) => marker.locations).find((item) => item.id === selectedLocationId);
    orbitFocusRef.current = location ? [location.longitude, location.latitude] : null;
    const selectedCase = selectedCaseId ? markers.find((marker) => marker.caseId === selectedCaseId) : null;
    const target = location ? [location.longitude, location.latitude] as [number, number] : selectedCase ? centerOf(selectedCase) : INDIA_CENTER;
    threeOverlayRef.current?.setTarget(target);
    mapRef.current?.triggerRepaint();
  }, [markers, selectedCaseId, selectedLocationId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const source = map.getSource("secret-data") as maplibregl.GeoJSONSource | undefined;
    source?.setData(buildData(markers, showCases, showLocations, showRoutes, selectedCaseId, selectedLocationId));
    if (map.getLayer("secret-location-labels")) map.setLayoutProperty("secret-location-labels", "visibility", showLabels && showLocations ? "visible" : "none");
    ["secret-route-glass", "secret-route-frost", "secret-routes"].forEach((layerId) => { if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", showRoutes ? "visible" : "none"); });
  }, [markers, showCases, showLocations, showRoutes, showLabels, selectedCaseId, selectedLocationId, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !cameraRequest) return;
    const request = cameraRequest;
    const state = useMapStore.getState();
    const resumeOrbit = orbitEnabledRef.current;
    stopOrbitRef.current();
    const resumeAfterFlight = () => { if (resumeOrbit && !orbitEnabledRef.current) startOrbitRef.current(); };
    if (resumeOrbit) map.once("moveend", resumeAfterFlight);
    if (request.kind === "reset") map.easeTo({ center: INDIA_CENTER, zoom: 3, pitch: 60, bearing: -14, duration: 1200, essential: true });
    else if (request.kind === "fit-all") fitAll(map, state.markers);
    else if (request.kind === "fit-point") {
      const zoomDist = request.zoomDist ?? 32;
      const zoom = zoomDist <= 26 ? 17 : zoomDist <= 40 ? 15 : 11.5;
      const pitch = zoomDist <= 26 ? 64 : zoomDist <= 40 ? 60 : 52;
      const target: [number, number] = [request.lon, request.lat];
      const camera = cinematicCameraOptions(map, target, map.getBearing() + 18, zoomDist <= 26 ? 220 : 420, zoomDist <= 26 ? 140 : 240);
      map.flyTo({ ...camera, zoom, pitch, bearing: map.getBearing() + 18, duration: 1500, essential: true });
    } else if (request.kind === "fit-location") {
      const location = state.locationById(request.locationId);
      if (location) {
        const target: [number, number] = [location.longitude, location.latitude];
        map.flyTo({ center: target, zoom: 21.5, pitch: 72, bearing: map.getBearing() + 18, duration: 2200, essential: true });
      }
    } else if (request.kind === "fit-case") {
      const marker = state.markers.find((item) => item.caseId === request.caseId);
      const location = marker ? primaryLocation(marker) : null;
      if (location) {
        const target: [number, number] = [location.longitude, location.latitude];
        // Zoom to the closest useful building-level view, approximately a
        // 50m operational radius around the selected case location.
        map.stop();
        map.flyTo({ center: target, zoom: 22, pitch: 74, bearing: map.getBearing() + 18, duration: 1400, essential: true });
      }
    }
  }, [cameraRequest, ready]);

  return (
    <div className="globe-shell maplibre-globe-shell">
      <div ref={hostRef} className="globe-canvas-host maplibre-map-host" />
      <div className="globe-scanlines" />
      <div className="globe-vignette" />
      {selectedMarker && <div className="map-selected-case" role="status">{selectedMarker.title}</div>}
      {hoveredMarker && hover && <div className="map-tooltip" style={{ left: Math.min(hover.x + 16, window.innerWidth - 270), top: Math.max(8, hover.y - 120) }}>
        <div className="map-tooltip-title">{hoveredMarker.caseId} · {hoveredMarker.title}</div>
        <div className="map-tooltip-row"><span>PRIORITY</span><strong className="map-tooltip-priority">{hoveredMarker.priority}</strong></div>
        <div className="map-tooltip-row"><span>LOCATIONS</span><strong>{hoveredMarker.locations.length}</strong></div>
        <div className="map-tooltip-row"><span>ENTITIES</span><strong>{hoveredMarker.entityIds.length}</strong></div>
      </div>}
      {hoveredLocation && hover && <div className="map-tooltip map-profile-tooltip" style={{ left: Math.min(hover.x + 16, window.innerWidth - 290), top: Math.max(8, hover.y - 150) }}>
        <div className="map-tooltip-kicker">CULPRIT PROFILE</div>
        <div className="map-tooltip-title">{hoveredEntities[0] ?? "Unidentified lead"}</div>
        <div className="map-tooltip-row"><span>LOCATION</span><strong>{hoveredLocation.name.split(" · ")[0]}</strong></div>
        <div className="map-tooltip-row"><span>STATUS</span><strong>{hoveredLocation.name.includes("detained") ? "DETAINED" : hoveredLocation.name.includes("report") ? "VEHICLE LEAD" : "INVESTIGATIVE LEAD"}</strong></div>
        <div className="map-tooltip-row"><span>LINKED</span><strong>{hoveredEntities.length > 1 ? `${hoveredEntities.length} ENTITIES` : "CASE EVIDENCE"}</strong></div>
        {hoveredEntities.length > 1 && <div className="map-tooltip-entities">{hoveredEntities.join(" · ")}</div>}
      </div>}
    </div>
  );
}
