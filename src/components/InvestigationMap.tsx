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
import maharashtraData from "../data/map/maharashtra.json";
import contextData from "../data/map/context.json";
import districtsData from "../data/map/maharashtra-districts.json";
import citiesData from "../data/map/cities.json";
import riversData from "../data/map/rivers.json";

// Layer thicknesses (world units): silhouettes below the Maharashtra chassis.
const INDIA_DEPTH = 0.3;
const CONTEXT_DEPTH = 0.42;
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
  if (!poly.length) return 0;
  let max = -1, idx = 0;
  poly.forEach((ring, i) => {
    let a = 0;
    for (let k = 0; k < ring.length - 1; k++) a += ring[k][0] * ring[k + 1][1] - ring[k + 1][0] * ring[k][1];
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

  const camera = new THREE.PerspectiveCamera(40, host.clientWidth / Math.max(1, host.clientHeight), 0.1, 900);
  const DEFAULT_TARGET = new THREE.Vector3(-121, 4, 9);
  const resetPos = () => {
    const DIST = 132;
    const elev = (46 * Math.PI) / 180;
    const az = -2.55;
    camera.position.set(
      DEFAULT_TARGET.x + Math.sin(az) * Math.cos(elev) * DIST,
      DEFAULT_TARGET.y + Math.sin(elev) * DIST,
      DEFAULT_TARGET.z + Math.cos(az) * Math.cos(elev) * DIST,
    );
  };
  resetPos();

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
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

  const midLat = (MAP_BOUNDS.minLat + MAP_BOUNDS.maxLat) / 2;
  const midLon = (MAP_BOUNDS.minLon + MAP_BOUNDS.maxLon) / 2;
  const indiaShape = buildExtruded(
    (indiaData as { polygons: Polygons }).polygons, toXY, INDIA_DEPTH,
    new THREE.MeshStandardMaterial({ color: 0x0a1628, transparent: true, opacity: 0.55, emissive: 0x0a1e3a, roughness: 0.95, metalness: 0.05, side: THREE.DoubleSide }),
  );
  const mahaShape = buildExtruded(
    (maharashtraData as { polygons: Polygons }).polygons, toXY, MAHA_DEPTH,
    new THREE.MeshStandardMaterial({ color: 0x12335c, emissive: 0x0c2950, roughness: 0.9, metalness: 0.1, flatShading: true, side: THREE.DoubleSide }),
  );
  geoGroup.add(indiaShape.group, mahaShape.group);

  // Adjacent-state silhouettes (named, for labels + realistic context).
  (contextData as { states: { name: string; polygons: Polygons }[] }).states.forEach((s) => {
    const built = buildExtruded(
      s.polygons, toXY, CONTEXT_DEPTH,
      new THREE.MeshStandardMaterial({ color: 0x0c1a35, transparent: true, opacity: 0.6, emissive: 0x0c2248, roughness: 0.95, metalness: 0.05, side: THREE.DoubleSide }),
    );
    geoGroup.add(built.group);
    addEdgeLines(built.edges, edgeMat(0x1f4c8a, 0.28), geoGroup, () => CONTEXT_DEPTH);
  });

  // ----- Relief terrain (displaced SRTM surface, clipped to Maharashtra) ---------
  const reliefGeo = new THREE.PlaneGeometry(
    (MAP_BOUNDS.maxLon - MAP_BOUNDS.minLon) * K_LON,
    (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat) * K_LAT,
    164, 128,
  );
  reliefGeo.rotateX(-Math.PI / 2);
  const rPos = reliefGeo.attributes.position as THREE.BufferAttribute;
  const colors = new Float32Array(rPos.count * 3);
  for (let i = 0; i < rPos.count; i += 1) {
    const x = rPos.getX(i), z = rPos.getZ(i);
    const lat = midLat + z / K_LAT;
    const lon = midLon + x / K_LON;
    rPos.setY(i, elevationWorldAt(lat, lon));
    const c = reliefVertexColor(elevationAt(lat, lon));
    colors[i * 3] = c[0] / 255; colors[i * 3 + 1] = c[1] / 255; colors[i * 3 + 2] = c[2] / 255;
  }
  reliefGeo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  reliefGeo.computeVertexNormals();
  const relief = new THREE.Mesh(reliefGeo, new THREE.MeshStandardMaterial({
    vertexColors: true,
    transparent: true,
    alphaMap: landMaskTexture(),
    alphaTest: 0.5,
    roughness: 0.97,
    metalness: 0.04,
    emissive: 0x0b2440,
    emissiveIntensity: 0.35,
    side: THREE.DoubleSide,
  }));
  geoGroup.add(relief);

  // --- District boundary lines riding the relief surface ---
  (districtsData as { districts: { name: string; polygons: Polygons }[] }).districts.forEach((d) => {
    d.polygons.forEach((poly) => {
      const ring = poly[outerRingIndex(poly)];
      const mumbai = MUMBAI_DISTRICTS.has(d.name);
      addEdgeLines(
        [ring.map(([lon, lat]) => { const p = toXY(lon, lat); return { x: p.x, z: p.y }; })],
        edgeMat(mumbai ? 0x6ff0ff : 0x2f86c9, mumbai ? 0.85 : 0.4),
        geoGroup,
        (x, z) => elevationWorldAtXY(x, z) + 0.3,
      );
    });
  });

  // State coastline (brightest) + silhouette edges on the relief.
  addEdgeLines(mahaShape.edges, edgeMat(0x8ff0ff, 0.7), geoGroup, (x, z) => elevationWorldAtXY(x, z) + 0.34);
  addEdgeLines(indiaShape.edges, edgeMat(0x15365e, 0.3), geoGroup, () => INDIA_DEPTH);

  // --- Rivers (static, on the terrain surface) ---
  (riversData as { rivers: { name: string; pts: number[][] }[] }).rivers.forEach((river) => {
    const pts = river.pts.map(([lon, lat]) => {
      const p = toXY(lon, lat);
      return new THREE.Vector3(p.x, elevationWorldAt(lat, lon) + 0.07, p.y);
    });
    if (pts.length < 2) return;
    const glowLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0x2696c8, 0.16),
    );
    const mainLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(pts),
      edgeMat(0x4cc3ef, 0.55),
    );
    geoGroup.add(glowLine, mainLine);
    if (RIVER_LABEL.has(river.name)) {
      const midIdx = Math.floor(pts.length / 2);
      const mid = pts[midIdx];
      const label = new THREE.Sprite(new THREE.SpriteMaterial({
        map: makeLabelTexture(river.name, "#7fc8ea"),
        transparent: true, depthWrite: false, opacity: 0.5,
      }));
      label.position.set(mid.x + 4, mid.y + 2.4, mid.z - 2);
      label.scale.set(Math.max(5, river.name.length * 1.45), 0.95, 1);
      staticGroup.add(label);
    }
  });

  // --- Labels: states, sea, region title, cities -----------------------------
  const labelAt = (text: string, color: string, lat: number, lon: number, yOff: number, widthMul = 1.5, size = 1, opacity = 0.62) => {
    const p = project(lat, lon);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: makeLabelTexture(text.toUpperCase(), color),
      transparent: true, depthWrite: false, opacity,
    }));
    sprite.position.set(p.x, Math.max(1.2, elevationWorldAt(lat, lon)) + yOff, p.y);
    sprite.scale.set(Math.max(6, text.length * widthMul * size), (0.95 + 0.32 * size) * size, 1);
    staticGroup.add(sprite);
  };
  (contextData as { states: { name: string; polygons: Polygons }[] }).states.forEach((s) => {
    const outer = s.polygons[0][outerRingIndex(s.polygons[0])];
    let lat = 0, lon = 0;
    outer.forEach((c) => { lat += c[1]; lon += c[0]; });
    const n = outer.length || 1;
    labelAt(s.name.replace(/^Dadra.*$/, "DADRA & DNH"), "#6f9fd8", lat / n, lon / n, 1.6, 1.5, 1.1, 0.45);
  });
  labelAt("Arabian Sea", "#4f86b8", 18.3, 71.55, 0.4, 1.3, 1.4, 0.4);
  labelAt("Maharashtra · India", "#7fb2ff", 19.6, 74.9, 3.2, 1.35, 1.5, 0.42);

  const cityDotTex = makeSpriteTexture(splitStyle(LOCATION_GLOW));
  (citiesData as { cities: { name: string; lat: number; lon: number; major?: boolean }[] }).cities.forEach((c) => {
    const p = project(c.lat, c.lon);
    const base = elevationWorldAt(c.lat, c.lon);
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({ map: cityDotTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    dot.material.color.setHex(c.major ? 0x9fe8ff : 0x5f8fc0);
    const s = c.major ? 2.6 : 1.4;
    dot.position.set(p.x, base + 0.5, p.y);
    dot.scale.set(s, s, 1);
    staticGroup.add(dot);
    labelAt(c.name, c.major ? "#dff8ff" : "#87b7e8", c.lat, c.lon, c.major ? 2.6 : 1.8, 1.45, c.major ? 1 : 0.8, 0.6);
  });

  // --- Dynamic marker / route state ----------------------------------------------
  const hitProbes: HitProbe[] = [];
  const comets: Comet[] = [];
  const pulse: PulseItem[] = [];
  const halos: Halo[] = [];
  const caseTexCache = new Map<string, THREE.CanvasTexture>();
  const labelTexCache = new Map<string, THREE.CanvasTexture>();
  const locTex = makeSpriteTexture(splitStyle(LOCATION_GLOW));
  const cometTex = makeSpriteTexture(splitStyle("rgba(255,255,255,1)|rgba(140,235,255,0.9)|rgba(40,90,180,0)"));

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
        const pos3 = new THREE.Vector3(cp.x, baseY + 2.0, cp.y);
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
          addLabel(m.caseId, isSel ? "#ffe9b0" : "#ffd27a", new THREE.Vector3(cp.x, pos3.y + 2.0, cp.y));
        }
      });
    }

    if (showLocations) {
      markers.forEach((m) => {
        m.locations.forEach((l) => {
          const p = project(l.latitude, l.longitude);
          const baseY = elevationWorldAt(l.latitude, l.longitude);
          const pos3 = new THREE.Vector3(p.x, baseY + 0.9, p.y);
          const active = locActive(l);
          const dimmed = locDimmed(l) || !locInRange(l);
          const scale = (0.8 + l.importance * 0.9) * (active ? 1.6 : dimmed ? 0.72 : 1.15);
          const hex = active ? 0xbff3ff : dimmed ? 0x2a6c9f : 0x4aa8e0;
          addSpriteAt(locTex, pos3, scale, hex, 1);
          addGroundGlow(pos3, scale * 3.4, dimmed ? 0x16304d : active ? 0x5adcff : 0x2f6f9f);
          addHalo(pos3, scale * 1.4, hex, active ? 0.34 : 0.12);
          addHitProbe("location", l.id, pos3, Math.max(0.6, scale * 0.72));
          if (showLabels) {
            addLabel(l.name, active ? "#dff8ff" : dimmed ? "#5f86a8" : "#8ec9f2", new THREE.Vector3(p.x, pos3.y + 1.5, p.y), 0.8);
          }
        });
      });
    }

    if (showRoutes && hasFocus) {
      markers.forEach((m) => {
        const cp = casePos.get(m.caseId);
        if (!cp || !m.locations.length) return;
        const focused = selCase?.caseId === m.caseId || selLoc?.caseId === m.caseId || m.locations.some((l) => entityLocIds.has(l.id));
        if (!focused) return;
        const baseY = elevationWorldAt(cp.y / K_LAT + (MAP_BOUNDS.minLat + MAP_BOUNDS.maxLat) / 2, cp.x / K_LON + (MAP_BOUNDS.minLon + MAP_BOUNDS.maxLon) / 2);
        const a = new THREE.Vector3(cp.x, baseY + 2.2, cp.y);
        m.locations.forEach((l, i) => {
          const p = project(l.latitude, l.longitude);
          const dim = locDimmed(l) || !locInRange(l);
          const b = new THREE.Vector3(p.x, elevationWorldAt(l.latitude, l.longitude) + 0.95, p.y);
          const mid = new THREE.Vector3((a.x + b.x) / 2, Math.max(a.y, b.y) + 4.5, (a.z + b.z) / 2);
          const line = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(28)),
            new THREE.LineBasicMaterial({
              color: 0x54dcff, transparent: true, opacity: dim ? 0.06 : 0.35,
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
      if (hit.userData.kind === "case") callbacks.onSelectCase(hit.userData.id);
      else callbacks.onSelectLocation(hit.userData.id);
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
function fitBounds(handle: SceneHandle, markers: CaseMarker[], caseId?: string) {
  const locs = caseId
    ? markers.find((m) => m.caseId === caseId)?.locations ?? []
    : markers.flatMap((m) => m.locations);
  if (!locs.length) return;
  const pts = locs.map((l) => project(l.latitude, l.longitude));
  const minX = Math.min(...pts.map((p) => p.x));
  const maxX = Math.max(...pts.map((p) => p.x));
  const minZ = Math.min(...pts.map((p) => p.y));
  const maxZ = Math.max(...pts.map((p) => p.y));
  const c = new THREE.Vector3((minX + maxX) / 2, CHASSIS_TOP + 2.5, (minZ + maxZ) / 2);
  const radius = Math.max(12, Math.hypot(maxX - minX, maxZ - minZ) * 0.62);
  const dir = handle.camera.position.clone().sub(handle.controls.target).normalize();
  handle.fly = { pos: c.clone().add(dir.multiplyScalar(radius * 2.0)), target: c.clone() };
}

function resetCamera(handle: SceneHandle) {
  const DIST = 132;
  const elev = (46 * Math.PI) / 180;
  const az = -2.55;
  const t = new THREE.Vector3(-121, 4, 9);
  handle.fly = {
    pos: new THREE.Vector3(t.x + Math.sin(az) * Math.cos(elev) * DIST, t.y + Math.sin(elev) * DIST, t.z + Math.cos(az) * Math.cos(elev) * DIST),
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
        else if (req.kind === "fit-all") fitBounds(h, state.markers);
        else resetCamera(h);
      }
    });
  }, []);

  const hoveredMarker = hover ? markers.find((m) => m.caseId === hover.id) : null;

  return (
    <div className="globe-shell">
      <div ref={hostRef} className="globe-canvas-host" />
      <div className="globe-scanlines" />
      <div className="globe-vignette" />
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