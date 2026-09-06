/**
 * InvestigationMap — interactive 3D geospatial intelligence map.
 *
 * Renders REAL geography from bundled data: SRTM elevation relief, Maharashtra
 * state + district outlines, Natural Earth rivers, real city points and state
 * labels. Case/location markers, routes, camera fit and network + timeline sync
 * come from `useMapStore` — the map contains no inherent data.
 *
 * Fully offline: everything is static under `src/data/map/`.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { useMapStore } from "../store/mapStore";
import { buildExtruded, type Polygons } from "./geoLayers";
import {
  project, toXY, elevationWorldAt, elevationWorldAtXY, elevationAt,
  landMaskTexture, reliefVertexColor, MAP_BOUNDS, CHASSIS_TOP, K_LAT, K_LON,
} from "./terrain";
import type { CaseLocation, CaseMarker } from "../types";
import indiaData from "../data/map/india.json";
import indiaStatesData from "../data/map/india-states.json";
import maharashtraData from "../data/map/maharashtra.json";
import contextData from "../data/map/context.json";
import districtsData from "../data/map/maharashtra-districts.json";
import citiesData from "../data/map/cities.json";
import riversData from "../data/map/rivers.json";
import transitData from "../data/map/transit.json";

// Layer thicknesses (world units):
const INDIA_DEPTH = 0.35;
const STATE_DEPTH = 0.42;
const MAHA_DEPTH = CHASSIS_TOP;

const MUMBAI_DISTRICTS = new Set(["Greater Bombay", "Thane"]);
const RIVER_LABEL = new Set(["Godävari", "Krishna"]);

// --- Marker palette ------------------------------------------------------------
const PRIORITY_SPRITE: Record<string, string> = {
  HIGH: "rgba(255,214,112,1)|rgba(255,162,44,0.92)|rgba(120,60,20,0)",
  MEDIUM: "rgba(223,248,255,1)|rgba(99,215,255,0.92)|rgba(40,80,160,0)",
  LOW: "rgba(223,248,238,1)|rgba(89,212,160,0.92)|rgba(30,100,70,0)",
};
const LOCATION_GLOW = "rgba(223,248,255,1)|rgba(99,215,255,0.85)|rgba(30,70,140,0)";
const TRAIN_STATION_GLOW = "rgba(255,230,160,1)|rgba(245,158,11,0.9)|rgba(120,60,10,0)";

function splitStyle(key: string): { inner: string; mid: string; outer: string } {
  const [inner, mid, outer] = key.split("|");
  return { inner, mid, outer };
}

// --- Texture helpers ------------------------------------------------------------
function makeSpriteTexture(style: { inner: string; mid: string; outer: string }): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  g.addColorStop(0, style.inner);
  g.addColorStop(0.2, style.mid);
  g.addColorStop(0.55, style.outer);
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeLabelTexture(text: string, color: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 64;
  const ctx = canvas.getContext("2d")!;
  ctx.font = "700 30px 'Fira Code', monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.shadowColor = "rgba(8,16,36,0.95)";
  ctx.shadowBlur = 10;
  ctx.fillStyle = color;
  ctx.fillText(text, 256, 32);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeOceanTexture(): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(256, 256, 40, 256, 256, 300);
  g.addColorStop(0, "#0a1f40");
  g.addColorStop(0.55, "#071830");
  g.addColorStop(1, "#03080f");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  ctx.strokeStyle = "rgba(56,140,220,0.10)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 8; i++) {
    ctx.beginPath();
    ctx.moveTo(i * 64, 0);
    ctx.lineTo(i * 64, 512);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, i * 64);
    ctx.lineTo(512, i * 64);
    ctx.stroke();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// --- Shared scene types ----------------------------------------------------------
type HitProbe = THREE.Mesh & { userData: { kind: string; id: string } };
type FlyState = { pos: THREE.Vector3; target: THREE.Vector3 };
type PulseItem = { sprite: THREE.Sprite; base: number; phase: number };

export type ViewInput = {
  markers: CaseMarker[];
  showCases: boolean;
  showLocations: boolean;
  showRoutes: boolean;
  showLabels: boolean;
  selectedCaseId: string | null;
  selectedLocationId: string | null;
  selectedEntityId: string | null;
  range: { start: string; end: string } | null;
};

type Comet = { sprite: THREE.Sprite; mat: THREE.SpriteMaterial; phase: number; curve: THREE.QuadraticBezierCurve3 };
type Halo = { ring: THREE.Mesh; baseScale: number; opacity: number };

type SceneHandle = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  hitProbes: HitProbe[];
  comets: Comet[];
  pulse: PulseItem[];
  halos: Halo[];
  fly: FlyState | null;
  rafId: number;
  dispose: () => void;
  update: (input: ViewInput) => void;
};

function inRange(ts: string, range: { start: string; end: string } | null): boolean {
  if (!range || !ts) return true;
  return ts >= range.start && ts <= range.end;
}

function disposeGroup(group: THREE.Group) {
  const walk = (node: THREE.Object3D) => {
    const mesh = node as THREE.Mesh;
    if (mesh.geometry) mesh.geometry.dispose();
    else if ("material" in node) {
      const mat = (node as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else if (mat) mat.dispose();
    }
    node.children.forEach(walk);
  };
  walk(group);
  group.clear();
}

/** Duplicate ring pairs into drawable line segments; per-vertex height via yFn. */
function addEdgeLines(
  edges: { x: number; z: number }[][],
  material: THREE.LineBasicMaterial,
  target: THREE.Group,
  yFn: (x: number, z: number) => number,
) {
  const geo = new THREE.BufferGeometry();
  const pts: THREE.Vector3[] = [];
  for (const ring of edges) {
    const vs = ring.map((p) => new THREE.Vector3(p.x, yFn(p.x, p.z), p.z));
    for (let i = 0; i < vs.length; i++) pts.push(vs[i], vs[(i + 1) % vs.length]);
  }
  geo.setFromPoints(pts);
  target.add(new THREE.LineSegments(geo, material));
}

function outerRingIndex(poly: number[][][]): number {
  if (!poly || !Array.isArray(poly) || !poly.length) return 0;
  let max = -1, idx = 0;
  poly.forEach((ring, i) => {
    if (!ring || !Array.isArray(ring) || ring.length < 2) return;
    let a = 0;
    for (let k = 0; k < ring.length - 1; k++) {
      if (Array.isArray(ring[k]) && Array.isArray(ring[k + 1])) {
        a += ring[k][0] * ring[k + 1][1] - ring[k + 1][0] * ring[k][1];
      }
    }
    const abs = Math.abs(a);
    if (abs > max) { max = abs; idx = i; }
  });
  return idx;
}

export function createInvestigationMap(
  host: HTMLDivElement,
  initial: ViewInput,
  callbacks: {
    onSelectCase: (id: string) => void;
    onSelectLocation: (id: string) => void;
    onClear: () => void;
    onHoverCase: (caseId: string | null, x: number, y: number) => void;
  },
): SceneHandle {
  let current = initial;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x02040a);
  scene.fog = new THREE.FogExp2(0x03060d, 0.0011);

  const camera = new THREE.PerspectiveCamera(40, host.clientWidth / Math.max(1, host.clientHeight), 0.1, 1500);
  const DEFAULT_TARGET = new THREE.Vector3(0, 4, 0);
  const resetPos = () => {
    const DIST = 340;
    const elev = (55 * Math.PI) / 180;
    const az = 0; // Standard geographic orientation: North is Up, South is Down
    camera.position.set(
      DEFAULT_TARGET.x + Math.sin(az) * Math.cos(elev) * DIST,
      DEFAULT_TARGET.y + Math.sin(elev) * DIST,
      DEFAULT_TARGET.z + Math.cos(elev) * DIST,
    );
  };
  resetPos();

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.setSize(host.clientWidth, Math.max(1, host.clientHeight));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x02040a, 1);
  renderer.shadowMap.enabled = false;
  host.appendChild(renderer.domElement);
  host.style.touchAction = "none";
  host.style.cursor = "grab";

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(DEFAULT_TARGET);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 22;
  controls.maxDistance = 620;
  controls.minPolarAngle = 0.35;
  controls.maxPolarAngle = 1.42;
  controls.update();

  scene.add(new THREE.AmbientLight(0x3a4a70, 1.1));
  const keyLight = new THREE.DirectionalLight(0xaac8ff, 1.5);
  keyLight.position.set(120, 220, -80);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0x37d7ff, 0.45);
  fillLight.position.set(-160, 90, 140);
  scene.add(fillLight);

  const geoGroup = new THREE.Group();
  const staticGroup = new THREE.Group();
  const markerGroup = new THREE.Group();
  const routeGroup = new THREE.Group();
  const labelGroup = new THREE.Group();
  scene.add(geoGroup, staticGroup, markerGroup, routeGroup, labelGroup);

  // Shared dynamic & probe arrays
  const hitProbes: HitProbe[] = [];
  const districtHitProbes: HitProbe[] = [];
  const comets: Comet[] = [];
  const pulse: PulseItem[] = [];
  const halos: Halo[] = [];
  const caseTexCache = new Map<string, THREE.CanvasTexture>();
  const labelTexCache = new Map<string, THREE.CanvasTexture>();
  const locTex = makeSpriteTexture(splitStyle(LOCATION_GLOW));
  const cometTex = makeSpriteTexture(splitStyle("rgba(255,255,255,1)|rgba(140,235,255,0.9)|rgba(40,90,180,0)"));

  // ----- Ocean surface --------------------------------------------------------
  const oceanGeo = new THREE.PlaneGeometry(720, 560);
  oceanGeo.rotateX(-Math.PI / 2);
  const ocean = new THREE.Mesh(oceanGeo, new THREE.MeshBasicMaterial({
    map: makeOceanTexture(),
    transparent: true,
    opacity: 0.9,
    depthWrite: false,
  }));
  ocean.position.y = -0.7;
  geoGroup.add(ocean);

  // ----- Static geography -------------------------------------------------------
  const edgeMat = (color: number, opacity: number) => new THREE.LineBasicMaterial({
    color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false,
  });

  const indiaShape = buildExtruded(
    (indiaData as { polygons: Polygons }).polygons, toXY, INDIA_DEPTH,
    new THREE.MeshStandardMaterial({ color: 0x0a1628, transparent: true, opacity: 0.55, emissive: 0x0a1e3a, roughness: 0.95, metalness: 0.05, side: THREE.DoubleSide }),
  );
  const mahaShape = buildExtruded(
    (maharashtraData as { polygons: Polygons }).polygons, toXY, MAHA_DEPTH,
    new THREE.MeshStandardMaterial({ color: 0x12335c, emissive: 0x0c2950, roughness: 0.9, metalness: 0.1, flatShading: true, side: THREE.DoubleSide }),
  );
  geoGroup.add(indiaShape.group, mahaShape.group);

  // Render All Indian States (Extruded polygons + glowing boundary lines)
  (indiaStatesData as { states: { name: string; polygons: Polygons }[] }).states.forEach((s) => {
    const isMaha = s.name === "Maharashtra";
    const depth = isMaha ? MAHA_DEPTH : STATE_DEPTH;
    const built = buildExtruded(
      s.polygons, toXY, depth,
      new THREE.MeshStandardMaterial({
        color: isMaha ? 0x143c6d : 0x0a1c36,
        emissive: isMaha ? 0x0c2950 : 0x08162d,
        roughness: 0.9,
        metalness: 0.1,
        flatShading: true,
        side: THREE.DoubleSide
      }),
    );
    geoGroup.add(built.group);
    addEdgeLines(
      built.edges,
      edgeMat(isMaha ? 0x8ff0ff : 0x3d7cc9, isMaha ? 0.8 : 0.45),
      geoGroup,
      () => depth + 0.05
    );
  });

  // Country outline glow
  addEdgeLines(indiaShape.edges, edgeMat(0x60b0ff, 0.75), geoGroup, () => INDIA_DEPTH + 0.08);

  // --- Maharashtra Perimeter Margin Boundary Line (Double Tactical Halo) ---
  addEdgeLines(mahaShape.edges, edgeMat(0x00f5ff, 0.95), geoGroup, () => MAHA_DEPTH + 0.16);
  addEdgeLines(mahaShape.edges, edgeMat(0x38bdf8, 0.4), geoGroup, () => MAHA_DEPTH + 0.32);

  // --- District boundary lines riding the Maharashtra relief surface ---
  if (districtsData && Array.isArray((districtsData as { districts?: unknown[] }).districts)) {
    (districtsData as { districts: { name: string; polygons: Polygons }[] }).districts.forEach((d) => {
      if (!d || !Array.isArray(d.polygons)) return;
      d.polygons.forEach((poly) => {
        if (!poly || !Array.isArray(poly) || !poly.length) return;
        const ring = poly[outerRingIndex(poly)] || poly[0];
        if (!ring || !Array.isArray(ring) || ring.length < 2) return;
        const mumbai = MUMBAI_DISTRICTS.has(d.name);
        const validPts = ring.filter((pt) => Array.isArray(pt) && pt.length >= 2 && typeof pt[0] === "number" && typeof pt[1] === "number");
        if (validPts.length < 2) return;
        addEdgeLines(
          [validPts.map(([lon, lat]) => { const p = toXY(lon, lat); return { x: p.x, z: -p.y }; })],
          edgeMat(mumbai ? 0x6ff0ff : 0x2f86c9, mumbai ? 0.75 : 0.35),
          geoGroup,
          (x, z) => elevationWorldAtXY(x, -z) + 0.2,
        );
      });
    });
  }

  // --- Maharashtra Imaginary Inter-District Connectivity Mesh & Margin Grid ---
  const districtNodes: { name: string; lat: number; lon: number }[] = [];
  if (districtsData && Array.isArray((districtsData as { districts?: unknown[] }).districts)) {
    (districtsData as { districts: { name: string; polygons: Polygons }[] }).districts.forEach((d) => {
      if (!d || !Array.isArray(d.polygons)) return;
      let latSum = 0, lonSum = 0, count = 0;
      d.polygons.forEach((poly) => {
        if (!poly || !Array.isArray(poly) || !poly.length) return;
        const ring = poly[outerRingIndex(poly)] || poly[0];
        if (ring && Array.isArray(ring)) {
          ring.forEach((pt) => {
            if (Array.isArray(pt) && pt.length >= 2 && typeof pt[0] === "number" && typeof pt[1] === "number") {
              lonSum += pt[0];
              latSum += pt[1];
              count += 1;
            }
          });
        }
      });
      if (count > 0) {
        districtNodes.push({ name: d.name, lat: latSum / count, lon: lonSum / count });
      }
    });
  }

  // Hub dot texture
  const hubTex = makeSpriteTexture(splitStyle("rgba(200,250,255,1)|rgba(0,229,255,0.9)|rgba(0,80,180,0)"));
  const connMeshMat = new THREE.LineBasicMaterial({
    color: 0x00e5ff,
    transparent: true,
    opacity: 0.38,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const connBackboneMat = new THREE.LineBasicMaterial({
    color: 0x38bdf8,
    transparent: true,
    opacity: 0.65,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });

  // Inter-district imaginary connectivity lines
  const connectedPairs = new Set<string>();
  const addConnectivityLine = (d1: { lat: number; lon: number; name: string }, d2: { lat: number; lon: number; name: string }, isBackbone = false) => {
    const key = [d1.name, d2.name].sort().join("::");
    if (connectedPairs.has(key)) return;
    connectedPairs.add(key);

    const p1 = project(d1.lat, d1.lon);
    const p2 = project(d2.lat, d2.lon);
    const y1 = elevationWorldAtXY(p1.x, p1.y) + 0.35;
    const y2 = elevationWorldAtXY(p2.x, p2.y) + 0.35;

    const numSegs = 16;
    const pts: THREE.Vector3[] = [];
    for (let k = 0; k <= numSegs; k++) {
      const t = k / numSegs;
      const x = THREE.MathUtils.lerp(p1.x, p2.x, t);
      const y = THREE.MathUtils.lerp(p1.y, p2.y, t);
      const elev = elevationWorldAtXY(x, y) + 0.35;
      const arc = Math.sin(t * Math.PI) * (isBackbone ? 2.5 : 1.2);
      pts.push(new THREE.Vector3(x, elev + arc, -y));
    }

    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      isBackbone ? connBackboneMat : connMeshMat,
    );
    geoGroup.add(line);
  };

  // Expose on window for runtime and console scripts
  if (typeof window !== "undefined") {
    (window as unknown as { MAHARASHTRA_DISTRICTS_DATA: unknown }).MAHARASHTRA_DISTRICTS_DATA = (districtsData as { districts: unknown }).districts;
  }

  // Connect nearest district neighbors (imaginary connectivity web)
  districtNodes.forEach((d1, i) => {
    // Add small telemetry node at district centroid
    const p = project(d1.lat, d1.lon);
    const base = elevationWorldAtXY(p.x, p.y);
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({ map: hubTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    dot.position.set(p.x, base + 0.45, -p.y);
    dot.scale.set(2.2, 2.2, 1);
    geoGroup.add(dot);

    // Hit probe for clicking and hovering on the district
    const probePos = new THREE.Vector3(p.x, base + 0.45, -p.y);
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(3.2, 6, 6),
      new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false }),
    );
    mesh.position.copy(probePos);
    mesh.userData = { kind: "district", id: d1.name, lat: d1.lat, lon: d1.lon };
    geoGroup.add(mesh);
    const probe = mesh as unknown as HitProbe;
    hitProbes.push(probe);
    districtHitProbes.push(probe);

    const neighbors = districtNodes
      .filter((_, idx) => idx !== i)
      .map((d2) => ({ d2, dist: Math.hypot(d1.lon - d2.lon, (d1.lat - d2.lat) * 1.05) }))
      .sort((a, b) => a.dist - b.dist)
      .slice(0, 3);

    neighbors.forEach(({ d2, dist }) => {
      if (dist < 1.75) {
        addConnectivityLine(d1, d2, false);
      }
    });
  });

  // Maharashtra express connectivity backbone corridors
  const findDistrict = (name: string) => districtNodes.find((d) => d.name.toLowerCase().includes(name.toLowerCase()));
  const mum = findDistrict("Bombay") || findDistrict("Thane") || { name: "Mumbai", lat: 18.94, lon: 72.84 };
  const pun = findDistrict("Pune") || { name: "Pune", lat: 18.52, lon: 73.86 };
  const ngp = findDistrict("Nagpur") || { name: "Nagpur", lat: 21.15, lon: 79.09 };
  const nsk = findDistrict("Nashik") || { name: "Nashik", lat: 19.99, lon: 73.79 };
  const aur = findDistrict("Aurangabad") || { name: "Aurangabad", lat: 19.87, lon: 75.34 };
  const klp = findDistrict("Kolhapur") || { name: "Kolhapur", lat: 16.70, lon: 74.24 };
  const slp = findDistrict("Solapur") || { name: "Solapur", lat: 17.65, lon: 75.90 };
  const nnd = findDistrict("Nanded") || { name: "Nanded", lat: 19.14, lon: 77.31 };
  const amr = findDistrict("Amravati") || { name: "Amravati", lat: 20.93, lon: 77.75 };

  if (mum && pun) addConnectivityLine(mum, pun, true);
  if (pun && aur) addConnectivityLine(pun, aur, true);
  if (aur && ngp) addConnectivityLine(aur, ngp, true); // Samruddhi connectivity trunk
  if (mum && nsk) addConnectivityLine(mum, nsk, true);
  if (nsk && aur) addConnectivityLine(nsk, aur, true);
  if (pun && klp) addConnectivityLine(pun, klp, true);
  if (pun && slp) addConnectivityLine(pun, slp, true);
  if (aur && nnd) addConnectivityLine(aur, nnd, true);
  if (amr && ngp) addConnectivityLine(amr, ngp, true);

  // --- Rivers ---
  (riversData as { rivers: { name: string; pts: number[][] }[] }).rivers.forEach((river) => {
    const pts = river.pts.map(([lon, lat]) => {
      const p = toXY(lon, lat);
      return new THREE.Vector3(p.x, elevationWorldAt(lat, lon) + 0.12, -p.y);
    });
    if (pts.length < 2) return;
    const glowLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0x2696c8, 0.25),
    );
    const mainLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0x4cc3ef, 0.65),
    );
    geoGroup.add(glowLine, mainLine);
    if (RIVER_LABEL.has(river.name)) {
      const midIdx = Math.floor(pts.length / 2);
      const mid = pts[midIdx];
      const label = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeLabelTexture(river.name, "#7fc8ea"),
        transparent: true, depthWrite: false, opacity: 0.6,
      }));
      label.position.set(mid.x + 4, mid.y + 2.4, mid.z - 2);
      label.scale.set(Math.max(5, river.name.length * 1.45), 0.95, 1);
      staticGroup.add(label);
    }
  });

  // --- National Highways / Major Road Corridors ---
  (transitData as { highways: { name: string; pts: number[][] }[]; railways: { name: string; pts: number[][] }[]; stations: { code: string; name: string; city: string; lat: number; lon: number }[] }).highways.forEach((hwy) => {
    const pts = hwy.pts.map(([lon, lat]) => {
      const p = toXY(lon, lat);
      return new THREE.Vector3(p.x, elevationWorldAt(lat, lon) + 0.16, -p.y);
    });
    if (pts.length < 2) return;
    const hwyLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0xf59e0b, 0.6), // Amber highway line
    );
    const hwyGlow = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0xfbbf24, 0.25),
    );
    geoGroup.add(hwyLine, hwyGlow);
  });

  // --- Railway Lines ---
  (transitData as { highways: { name: string; pts: number[][] }[]; railways: { name: string; pts: number[][] }[]; stations: { code: string; name: string; city: string; lat: number; lon: number }[] }).railways.forEach((rail) => {
    const pts = rail.pts.map(([lon, lat]) => {
      const p = toXY(lon, lat);
      return new THREE.Vector3(p.x, elevationWorldAt(lat, lon) + 0.18, -p.y);
    });
    if (pts.length < 2) return;
    const railLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0x60a5fa, 0.75), // Bright rail corridor
    );
    const railGlow = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0x93c5fd, 0.3),
    );
    geoGroup.add(railLine, railGlow);
  });

  // --- Labels: Indian States, Sea, Cities, Train Stations -----------------------------
  const labelAt = (text: string, color: string, lat: number, lon: number, yOff: number, widthMul = 2.0, size = 1.4, opacity = 0.85) => {
    const p = project(lat, lon);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: makeLabelTexture(text.toUpperCase(), color),
      transparent: true, depthWrite: false, opacity,
    }));
    sprite.position.set(p.x, Math.max(1.5, elevationWorldAt(lat, lon)) + yOff, -p.y);
    sprite.scale.set(Math.max(10, text.length * widthMul * size), 3.2 * size, 1);
    staticGroup.add(sprite);
  };

  // State Name Labels (positioned at primary polygon centroid)
  (indiaStatesData as { states: { name: string; polygons: Polygons }[] }).states.forEach((s) => {
    let maxRing: number[][] = [];
    let maxLen = 0;
    s.polygons.forEach((poly) => {
      const ring = poly[outerRingIndex(poly)] || poly[0];
      if (ring && ring.length > maxLen) {
        maxLen = ring.length;
        maxRing = ring;
      }
    });
    if (!maxRing.length) return;
    let latSum = 0, lonSum = 0;
    maxRing.forEach(([lon, lat]) => {
      latSum += lat;
      lonSum += lon;
    });
    const avgLat = latSum / maxRing.length;
    const avgLon = lonSum / maxRing.length;
    const isMaha = s.name === "Maharashtra";
    labelAt(
      s.name,
      isMaha ? "#e0f8ff" : "#b0d4ff",
      avgLat,
      avgLon,
      isMaha ? 3.8 : 2.4,
      1.8,
      isMaha ? 1.6 : 1.2,
      isMaha ? 0.95 : 0.85
    );
  });

  labelAt("Arabian Sea", "#60a5fa", 16.5, 69.5, 0.6, 2.0, 1.8, 0.75);
  labelAt("Bay of Bengal", "#60a5fa", 15.5, 87.5, 0.6, 2.0, 1.8, 0.75);
  labelAt("India · National Grid", "#60a5fa", 23.5, 79.5, 5.0, 2.2, 2.2, 0.85);

  // Major Cities
  const cityDotTex = makeSpriteTexture(splitStyle(LOCATION_GLOW));
  (citiesData as { cities: { name: string; lat: number; lon: number; major?: boolean }[] }).cities.forEach((c) => {
    const p = project(c.lat, c.lon);
    const base = elevationWorldAt(c.lat, c.lon);
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({ map: cityDotTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    dot.material.color.setHex(c.major ? 0x9fe8ff : 0x5f8fc0);
    const s = c.major ? 4.5 : 2.8;
    dot.position.set(p.x, base + 0.8, -p.y);
    dot.scale.set(s, s, 1);
    staticGroup.add(dot);
    labelAt(c.name, c.major ? "#ffffff" : "#c2e0ff", c.lat, c.lon, c.major ? 4.0 : 2.8, 2.0, c.major ? 1.4 : 1.0, 0.9);
  });

  // Major Train Stations / Railway Terminals
  const stationDotTex = makeSpriteTexture(splitStyle(TRAIN_STATION_GLOW));
  (transitData as { stations: { code: string; name: string; city: string; lat: number; lon: number }[] }).stations.forEach((st) => {
    const p = project(st.lat, st.lon);
    const base = elevationWorldAt(st.lat, st.lon);
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({ map: stationDotTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    dot.material.color.setHex(0xfbbf24);
    dot.position.set(p.x, base + 1.0, -p.y);
    dot.scale.set(3.6, 3.6, 1);
    staticGroup.add(dot);
    labelAt(`🚉 ${st.code} · ${st.name}`, "#fde68a", st.lat, st.lon, 4.6, 2.0, 1.1, 0.88);
  });

  // --- Dynamic marker / route helpers ----------------------------------------------

  const addSpriteAt = (tex: THREE.Texture, pos3: THREE.Vector3, scale: number, colorHex: number, base: number | null): THREE.Sprite => {
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    mat.color.setHex(colorHex);
    const sprite = new THREE.Sprite(mat);
    sprite.position.copy(pos3);
    sprite.scale.set(scale, scale, 1);
    markerGroup.add(sprite);
    if (base !== null) pulse.push({ sprite, base, phase: Math.random() * Math.PI * 2 });
    return sprite;
  };

  const addHitProbe = (kind: string, id: string, pos3: THREE.Vector3, radius: number) => {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 6, 6),
      new THREE.MeshBasicMaterial({ colorWrite: false, depthWrite: false }),
    );
    mesh.position.copy(pos3);
    mesh.userData = { kind, id };
    markerGroup.add(mesh);
    hitProbes.push(mesh as unknown as HitProbe);
  };

  const addGroundGlow = (pos3: THREE.Vector3, scale: number, colorHex: number) => {
    const mat = new THREE.SpriteMaterial({ map: locTex, transparent: true, opacity: 0.13, depthWrite: false, blending: THREE.AdditiveBlending });
    mat.color.setHex(colorHex);
    const s = new THREE.Sprite(mat);
    s.position.set(pos3.x, pos3.y - 0.2, pos3.z);
    s.scale.set(scale, scale, 1);
    markerGroup.add(s);
  };

  const addHalo = (pos3: THREE.Vector3, scale: number, colorHex: number, opacity: number, pulsing = false) => {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.55, 0.78, 28),
      new THREE.MeshBasicMaterial({
        color: colorHex, transparent: true, opacity, side: THREE.DoubleSide,
        depthWrite: false, blending: THREE.AdditiveBlending,
      }),
    );
    ring.position.copy(pos3);
    ring.rotation.x = -Math.PI / 2;
    ring.scale.setScalar(scale);
    markerGroup.add(ring);
    if (pulsing) halos.push({ ring, baseScale: scale, opacity });
  };

  const addLabel = (text: string, color: string, pos3: THREE.Vector3, scaleMul = 1) => {
    const cacheKey = `${text}:${color}`;
    let tex = labelTexCache.get(cacheKey);
    if (!tex) {
      tex = makeLabelTexture(text.toUpperCase(), color);
      labelTexCache.set(cacheKey, tex);
    }
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, opacity: 0.85 });
    const sprite = new THREE.Sprite(mat);
    sprite.position.copy(pos3);
    sprite.scale.set(Math.max(2.2, text.length * 1.35 * scaleMul), 0.68 * scaleMul, 1);
    labelGroup.add(sprite);
  };

  const addComet = (a: THREE.Vector3, b: THREE.Vector3, phase: number) => {
    const mid = new THREE.Vector3((a.x + b.x) / 2, Math.max(a.y, b.y) + (3 + Math.min(3.5, a.distanceTo(b) * 0.06)), (a.z + b.z) / 2);
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const mat = new THREE.SpriteMaterial({ map: cometTex, transparent: true, opacity: 0.9, depthWrite: false, blending: THREE.AdditiveBlending });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(1.1, 1.1, 1);
    routeGroup.add(sprite);
    comets.push({ sprite, mat, phase, curve });
  };

  // ----- Data rebuild ----------------------------------------------------------
  const rebuild = () => {
    disposeGroup(markerGroup);
    disposeGroup(routeGroup);
    disposeGroup(labelGroup);
    hitProbes.length = 0;
    hitProbes.push(...districtHitProbes);
    comets.length = 0;
    pulse.length = 0;
    halos.length = 0;

    const { markers, selectedCaseId, selectedLocationId, selectedEntityId, range, showCases, showLocations, showRoutes, showLabels } = current;
    const allLocs = markers.flatMap((m) => m.locations);
    const selCase = markers.find((m) => m.caseId === selectedCaseId) ?? null;
    const selLoc = allLocs.find((l) => l.id === selectedLocationId) ?? null;
    const entityLocIds = new Set(useMapStore.getState().locationsForEntity(selectedEntityId ?? "").map((l) => l.id));
    const hasFocus = !!(selCase || selLoc || selectedEntityId);

    const casePos = new Map<string, { x: number; y: number }>();
    {
      const positioned: { x: number; y: number }[] = [];
      markers.filter((m) => m.locations.length).slice().sort((a, b) => a.caseId.localeCompare(b.caseId)).forEach((m) => {
        const lat = m.locations.reduce((s, l) => s + l.latitude, 0) / m.locations.length;
        const lon = m.locations.reduce((s, l) => s + l.longitude, 0) / m.locations.length;
        const p = project(lat, lon);
        let px = p.x, py = p.y;
        let guard = 0;
        while (positioned.some((o) => Math.hypot(px - o.x, py - o.y) < 5.5) && guard < 10) {
          let dx = 0, dy = 0;
          positioned.forEach((o) => {
            const d = Math.hypot(px - o.x, py - o.y);
            if (d < 1e-6) { dx += 1; }
            else if (d < 5.5) { dx += ((px - o.x) / d) * 1.6; dy += ((py - o.y) / d) * 1.6; }
          });
          px += dx; py += dy; guard += 1;
        }
        positioned.push({ x: px, y: py });
        casePos.set(m.caseId, { x: px, y: py });
      });
    }

    const caseDimmed = (m: CaseMarker) => {
      if (!hasFocus) return false;
      if (selCase) return m.caseId !== selCase.caseId;
      if (selLoc) return m.caseId !== selLoc.caseId;
      return !m.locations.some((l) => entityLocIds.has(l.id));
    };
    const locDimmed = (l: CaseLocation) => {
      if (!hasFocus) return false;
      if (selLoc) return l.id !== selLoc.id;
      if (selCase) return l.caseId !== selCase.caseId;
      return !entityLocIds.has(l.id);
    };
    const locActive = (l: CaseLocation) => !!(selLoc && l.id === selLoc.id) || !!(selCase && l.caseId === selCase.caseId) || entityLocIds.has(l.id);
    const locInRange = (l: CaseLocation) => {
      if (!range) return true;
      const locEvents = markers.find((m) => m.caseId === l.caseId)?.events.filter((e) => e.locationId === l.id) ?? [];
      if (!locEvents.length) return true;
      return locEvents.some((e) => inRange(e.timestamp, range));
    };

    if (showCases) {
      markers.forEach((m) => {
        const cp = casePos.get(m.caseId);
        if (!cp) return;
        const baseY = elevationWorldAt(cp.y / K_LAT + (MAP_BOUNDS.minLat + MAP_BOUNDS.maxLat) / 2, cp.x / K_LON + (MAP_BOUNDS.minLon + MAP_BOUNDS.maxLon) / 2);
        const pos3 = new THREE.Vector3(cp.x, baseY + 2.0, -cp.y);
        const isSel = m.caseId === selectedCaseId;
        const dimmed = caseDimmed(m);
        const hex = m.priority === "HIGH" ? 0xffd46a : m.priority === "MEDIUM" ? 0x6fdcff : 0x5ad592;
        const key = PRIORITY_SPRITE[m.priority] ?? PRIORITY_SPRITE.LOW;
        let caseTex = caseTexCache.get(key);
        if (!caseTex) {
          caseTex = makeSpriteTexture(splitStyle(key));
          caseTexCache.set(key, caseTex);
        }
        addSpriteAt(caseTex, pos3, isSel ? 3.0 : dimmed ? 1.5 : 2.3, hex, 1);
        addHalo(pos3, isSel ? 3.2 : 2.2, hex, isSel ? 0.5 : 0.16);
        if (isSel) addHalo(pos3, 3.8, 0xffffff, 0.42, true);
        addHitProbe("case", m.caseId, pos3, 1.8);
        if (showLabels) {
          addLabel(m.caseId, isSel ? "#ffe9b0" : "#ffd27a", new THREE.Vector3(cp.x, pos3.y + 2.0, -cp.y));
        }
      });
    }

    if (showLocations) {
      markers.forEach((m) => {
        m.locations.forEach((l) => {
          const p = project(l.latitude, l.longitude);
          const baseY = elevationWorldAt(l.latitude, l.longitude);
          const pos3 = new THREE.Vector3(p.x, baseY + 0.9, -p.y);
          const active = locActive(l);
          const dimmed = locDimmed(l) || !locInRange(l);
          const scale = (0.8 + l.importance * 0.9) * (active ? 1.6 : dimmed ? 0.72 : 1.15);
          const hex = active ? 0xbff3ff : dimmed ? 0x2a6c9f : 0x4aa8e0;
          addSpriteAt(locTex, pos3, scale, hex, 1);
          addGroundGlow(pos3, scale * 3.4, dimmed ? 0x16304d : active ? 0x5adcff : 0x2f6f9f);
          addHalo(pos3, scale * 1.4, hex, active ? 0.34 : 0.12);
          addHitProbe("location", l.id, pos3, Math.max(0.6, scale * 0.72));
          if (showLabels) {
            addLabel(l.name, active ? "#dff8ff" : dimmed ? "#5f86a8" : "#8ec9f2", new THREE.Vector3(p.x, pos3.y + 1.5, -p.y), 0.8);
          }
        });
      });
    }

    if (showRoutes) {
      markers.forEach((m) => {
        const cp = casePos.get(m.caseId);
        if (!cp || !m.locations.length) return;
        const focused = !hasFocus || selCase?.caseId === m.caseId || selLoc?.caseId === m.caseId || m.locations.some((l) => entityLocIds.has(l.id));
        if (hasFocus && !focused) return;
        const baseY = elevationWorldAt(cp.y / K_LAT + (MAP_BOUNDS.minLat + MAP_BOUNDS.maxLat) / 2, cp.x / K_LON + (MAP_BOUNDS.minLon + MAP_BOUNDS.maxLon) / 2);
        const a = new THREE.Vector3(cp.x, baseY + 2.2, -cp.y);
        m.locations.forEach((l, i) => {
          const p = project(l.latitude, l.longitude);
          const dim = hasFocus && (locDimmed(l) || !locInRange(l));
          const b = new THREE.Vector3(p.x, elevationWorldAt(l.latitude, l.longitude) + 0.95, -p.y);
          const mid = new THREE.Vector3((a.x + b.x) / 2, Math.max(a.y, b.y) + 4.5, (a.z + b.z) / 2);
          const line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(28)),
            new THREE.LineBasicMaterial({
              color: 0x54dcff, transparent: true, opacity: dim ? 0.08 : 0.4,
              blending: THREE.AdditiveBlending, depthWrite: false,
            }),
          );
          routeGroup.add(line);
          if (!dim) addComet(a, b, i * 0.35);
        });
      });
    }
  };
  rebuild();

  // ----- Selection / hover / drag -----------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const updateNdc = (e: PointerEvent) => {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / Math.max(1, r.width)) * 2 - 1, -(((e.clientY - r.top) / Math.max(1, r.height)) * 2 - 1));
  };
  const pickAt = () => {
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(hitProbes, false)[0];
    return hit?.object as unknown as HitProbe | undefined;
  };
  const drag = { x: 0, y: 0, moved: false, down: false };

  const onPointerMove = (e: PointerEvent) => {
    updateNdc(e);
    if (drag.down) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 6) drag.moved = true;
      host.style.cursor = "grabbing";
    }
    const hit = pickAt();
    if (hit && hit.userData.kind === "case") {
      host.style.cursor = "pointer";
      callbacks.onHoverCase(hit.userData.id, e.clientX, e.clientY);
    } else if (hit && hit.userData.kind === "district") {
      host.style.cursor = "pointer";
      callbacks.onHoverCase(`DISTRICT:${hit.userData.id}:${hit.userData.lat}:${hit.userData.lon}`, e.clientX, e.clientY);
    } else {
      host.style.cursor = drag.down ? "grabbing" : "grab";
      callbacks.onHoverCase(null, 0, 0);
    }
  };
  const onPointerDown = (e: PointerEvent) => {
    updateNdc(e);
    drag.x = e.clientX;
    drag.y = e.clientY;
    drag.moved = false;
    drag.down = true;
  };
  const onPointerUp = (e: PointerEvent) => {
    const wasMoved = drag.moved;
    drag.down = false;
    updateNdc(e);
    if (wasMoved) return;
    const hit = pickAt();
    if (hit) {
      if (hit.userData.kind === "case") {
        callbacks.onSelectCase(hit.userData.id);
      } else if (hit.userData.kind === "district") {
        // Fly directly to district
        const lat = Number(hit.userData.lat);
        const lon = Number(hit.userData.lon);
        const p = project(lat, lon);
        const baseY = elevationWorldAtXY(p.x, p.y);
        const c = new THREE.Vector3(p.x, baseY + 1.5, -p.y);
        const elev = (50 * Math.PI) / 180;
        const dir = new THREE.Vector3(0, Math.sin(elev), Math.cos(elev));
        handle.fly = { pos: c.clone().add(dir.multiplyScalar(32)), target: c.clone() };
      } else {
        callbacks.onSelectLocation(hit.userData.id);
      }
    } else {
      callbacks.onClear();
    }
  };

  renderer.domElement.addEventListener("pointermove", onPointerMove);
  renderer.domElement.addEventListener("pointerdown", onPointerDown);
  renderer.domElement.addEventListener("pointerup", onPointerUp);

  // ----- Frame loop ---------------------------------------------------------------
  const handle: SceneHandle = {
    scene, camera, renderer, controls, hitProbes, comets, pulse, halos, fly: null, rafId: 0,
    dispose: () => {},
    update: () => {},
  };

  const t0 = performance.now();
  const animate = () => {
    handle.rafId = requestAnimationFrame(animate);
    const t = (performance.now() - t0) * 0.001;
    if (handle.fly) {
      camera.position.lerp(handle.fly.pos, 0.08);
      controls.target.lerp(handle.fly.target, 0.12);
      if (camera.position.distanceTo(handle.fly.pos) < 0.4) handle.fly = null;
    }
    controls.update();

    pulse.forEach((item) => {
      const s = item.base * (1 + 0.09 * Math.sin(t * 3 + item.phase));
      item.sprite.scale.set(s, s, 1);
    });
    halos.forEach((h) => {
      const s = h.baseScale * (1 + 0.22 * Math.sin(t * 2.4));
      h.ring.scale.set(s, s, s);
      (h.ring.material as THREE.MeshBasicMaterial).opacity = h.opacity * (0.72 + 0.28 * Math.sin(t * 2.4 + 1.2));
    });
    comets.forEach((c) => {
      const p = (t * 0.16 + c.phase) % 1;
      c.sprite.position.copy(c.curve.getPoint(p));
      c.mat.opacity = 0.35 + 0.55 * Math.sin(p * Math.PI);
    });

    renderer.render(scene, camera);
  };
  animate();

  const onResize = () => {
    const w = host.clientWidth;
    const h = Math.max(1, host.clientHeight);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  };
  window.addEventListener("resize", onResize);

  handle.update = (input) => {
    current = input;
    rebuild();
  };

  handle.dispose = () => {
    cancelAnimationFrame(handle.rafId);
    window.removeEventListener("resize", onResize);
    renderer.domElement.removeEventListener("pointermove", onPointerMove);
    renderer.domElement.removeEventListener("pointerdown", onPointerDown);
    renderer.domElement.removeEventListener("pointerup", onPointerUp);
    controls.dispose();
    disposeGroup(markerGroup);
    disposeGroup(routeGroup);
    disposeGroup(labelGroup);
    disposeGroup(geoGroup);
    disposeGroup(staticGroup);
    oceanGeo.dispose();
    locTex.dispose();
    cometTex.dispose();
    cityDotTex.dispose();
    caseTexCache.forEach((tex) => tex.dispose());
    labelTexCache.forEach((tex) => tex.dispose());
    renderer.dispose();
    if (renderer.domElement.parentElement === host) host.removeChild(renderer.domElement);
  };

  return handle;
}

// --- Fly-to -----------------------------------------------------------------------
function fitBounds(handle: SceneHandle, markers: CaseMarker[], caseId?: string, locationId?: string) {
  let targetLocs: CaseLocation[] = [];
  if (locationId) {
    const l = markers.flatMap((m) => m.locations).find((loc) => loc.id === locationId);
    if (l) targetLocs = [l];
  } else if (caseId) {
    targetLocs = markers.find((m) => m.caseId === caseId)?.locations ?? [];
  } else {
    targetLocs = markers.flatMap((m) => m.locations);
  }

  if (!targetLocs.length) return;
  const pts = targetLocs.map((l) => project(l.latitude, l.longitude));
  const minX = Math.min(...pts.map((p) => p.x));
  const maxX = Math.max(...pts.map((p) => p.x));
  const minZ = Math.min(...pts.map((p) => -p.y));
  const maxZ = Math.max(...pts.map((p) => -p.y));
  const c = new THREE.Vector3((minX + maxX) / 2, CHASSIS_TOP + 2.5, (minZ + maxZ) / 2);
  const span = Math.hypot(maxX - minX, maxZ - minZ);
  const radius = Math.max(14, span * 0.65);

  let dir = handle.camera.position.clone().sub(handle.controls.target);
  if (dir.lengthSq() < 1e-4) {
    const elev = (55 * Math.PI) / 180;
    dir = new THREE.Vector3(0, Math.sin(elev), Math.cos(elev));
  } else {
    dir.normalize();
  }
  const dist = locationId ? 38 : Math.max(28, radius * 2.2);
  handle.fly = { pos: c.clone().add(dir.multiplyScalar(dist)), target: c.clone() };
}

function flyToPoint(handle: SceneHandle, lat: number, lon: number, zoomDist = 34) {
  const p = project(lat, lon);
  const elevY = elevationWorldAtXY(p.x, p.y);
  const c = new THREE.Vector3(p.x, Math.max(1.6, elevY + 1.2), -p.y);
  let dir = handle.camera.position.clone().sub(handle.controls.target);
  if (dir.lengthSq() < 1e-4) {
    const elev = (55 * Math.PI) / 180;
    dir = new THREE.Vector3(0, Math.sin(elev), Math.cos(elev));
  } else {
    dir.normalize();
  }
  handle.fly = { pos: c.clone().add(dir.multiplyScalar(zoomDist)), target: c.clone() };
}

function resetCamera(handle: SceneHandle) {
  const DIST = 340;
  const elev = (55 * Math.PI) / 180;
  const az = 0;
  const t = new THREE.Vector3(0, 4, 0);
  handle.fly = {
    pos: new THREE.Vector3(t.x + Math.sin(az) * Math.cos(elev) * DIST, t.y + Math.sin(elev) * DIST, t.z + Math.cos(elev) * DIST),
    target: t,
  };
}

// --- React wrapper -------------------------------------------------------------------
export function InvestigationMap() {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const handleRef = useRef<SceneHandle | null>(null);
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);

  const markers = useMapStore((s) => s.markers);
  const showCases = useMapStore((s) => s.showCases);
  const showLocations = useMapStore((s) => s.showLocations);
  const showRoutes = useMapStore((s) => s.showRoutes);
  const showLabels = useMapStore((s) => s.showLabels);
  const selectedCaseId = useMapStore((s) => s.selectedCaseId);
  const selectedLocationId = useMapStore((s) => s.selectedLocationId);
  const selectedEntityId = useMapStore((s) => s.selectedEntityId);
  const range = useMapStore((s) => s.range);

  const input = useMemo<ViewInput>(() => ({
    markers, showCases, showLocations, showRoutes, showLabels,
    selectedCaseId, selectedLocationId, selectedEntityId, range,
  }), [markers, showCases, showLocations, showRoutes, showLabels, selectedCaseId, selectedLocationId, selectedEntityId, range]);

  const callbacks = useMemo(() => ({
    onSelectCase: (id: string) => {
      const store = useMapStore.getState();
      store.selectCase(id);
      store.selectEntity(null);
      store.requestCamera("fit-case", id);
      setHover(null);
    },
    onSelectLocation: (id: string) => {
      const store = useMapStore.getState();
      const loc = store.locationById(id);
      store.selectLocation(id);
      store.selectEntity(loc?.entityIds[0] ?? null);
      store.requestCamera("fit-location", id);
    },
    onClear: () => useMapStore.getState().clearSelection(),
    onHoverCase: (caseId: string | null, x: number, y: number) => setHover(caseId ? { id: caseId, x, y } : null),
  }), []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const handle = createInvestigationMap(host, input, callbacks);
    handleRef.current = handle;
    return () => {
      handle.dispose();
      handleRef.current = null;
    };
  }, []);

  useEffect(() => {
    handleRef.current?.update(input);
  }, [input]);

  useEffect(() => {
    const store = useMapStore;
    return store.subscribe((state, prev) => {
      const req = state.cameraRequest;
      if (req && req !== prev.cameraRequest) {
        const h = handleRef.current;
        if (!h) return;
        if (req.kind === "fit-case") fitBounds(h, state.markers, req.caseId);
        else if (req.kind === "fit-location") fitBounds(h, state.markers, undefined, req.locationId);
        else if (req.kind === "fit-point") flyToPoint(h, req.lat, req.lon, req.zoomDist);
        else if (req.kind === "fit-all") fitBounds(h, state.markers);
        else resetCamera(h);
      }
    });
  }, []);

  const isDistrictHover = hover?.id.startsWith("DISTRICT:");
  const districtInfo = isDistrictHover ? (() => {
    const [, name, lat, lon] = hover!.id.split(":");
    return { name, lat: Number(lat).toFixed(3), lon: Number(lon).toFixed(3) };
  })() : null;
  const hoveredMarker = hover && !isDistrictHover ? markers.find((m) => m.caseId === hover.id) : null;

  return (
    <div className="globe-shell">
      <div ref={hostRef} className="globe-canvas-host" />
      <div className="globe-scanlines" />
      <div className="globe-vignette" />
      {districtInfo && (
        <div
          className="map-tooltip"
          style={{ left: Math.min(hover!.x + 16, window.innerWidth - 270), top: Math.max(8, hover!.y - 120) }}
        >
          <div className="map-tooltip-title">📍 {districtInfo.name} District</div>
          <div className="map-tooltip-row"><span>STATE</span><strong style={{ color: "#38bdf8" }}>Maharashtra</strong></div>
          <div className="map-tooltip-row"><span>GRID SECTOR</span><strong>Deccan Telemetry Mesh</strong></div>
          <div className="map-tooltip-row"><span>COORDINATES</span><strong style={{ fontFamily: "monospace" }}>{districtInfo.lat}° N, {districtInfo.lon}° E</strong></div>
          <div className="map-tooltip-row"><span>STATUS</span><strong style={{ color: "#4ade80" }}>● CONNECTED / ACTIVE</strong></div>
        </div>
      )}
      {hoveredMarker && (
        <div
          className="map-tooltip"
          style={{ left: Math.min(hover!.x + 16, window.innerWidth - 250), top: Math.max(8, hover!.y - 120) }}
        >
          <div className="map-tooltip-title">{hoveredMarker.caseId} · {hoveredMarker.title}</div>
          <div className="map-tooltip-row"><span>PRIORITY</span><strong className="map-tooltip-priority">{hoveredMarker.priority}</strong></div>
          <div className="map-tooltip-row"><span>LOCATIONS</span><strong>{hoveredMarker.locations.length}</strong></div>
          <div className="map-tooltip-row"><span>ENTITIES</span><strong>{hoveredMarker.entityIds.length}</strong></div>
          <div className="map-tooltip-row"><span>LAST ACTIVITY</span><strong>{hoveredMarker.lastActivity ? new Date(hoveredMarker.lastActivity).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</strong></div>
        </div>
      )}
    </div>
  );
}