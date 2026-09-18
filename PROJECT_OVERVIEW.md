# SECRET Project Overview and Technical Approach

**Project:** SECRET - Strategic Entity & Criminal Relationship Exploration Tool  
**Repository:** `Vedh28/NEW_SECRET` (development target; `Vedh28/SECRET_` is legacy reference only)  
**Status:** Working full-stack demo with React frontend, FastAPI backend, relational and graph persistence, ingestion, analytics, reports, and a MapLibre-based 3D intelligence map.

## 1. Purpose

SECRET is an investigative intelligence and decision-support application. It combines fragmented synthetic records into a searchable case workspace containing:

- cases and investigations;
- people, organizations, phones, vehicles, accounts, and locations;
- typed relationships and network visualizations;
- communications, transactions, timeline, and location views;
- anomaly, risk, priority, and hidden-link indicators;
- alerts, investigative leads, simulations, audit events, and PDF reports;
- a dark operational command center with an interactive 3D city map.

The system produces indicators and evidence-backed leads. It must not be interpreted as a declaration of guilt. The repository currently uses synthetic or fictional data for the demo flow.

## 2. High-Level Architecture

```text
                          SECRET desktop/web UI
       +-----------------------------------------------------------+
       | React 19 + TypeScript + Vite                             |
       | Zustand state | HUD CSS | React Flow | Recharts/D3       |
       | MapLibre GL + Three.js map overlay                       |
       +---------------------------+-------------------------------+
                                   |
                  typed JSON over HTTP; Bearer JWT when authenticated
                                   |
       +---------------------------v-------------------------------+
       | FastAPI backend                                            |
       | API routers -> services -> repositories / analytics       |
       | ingestion -> normalized records -> persistence            |
       +--------------------+--------------------+------------------+
                            |                    |
                 PostgreSQL relational       Neo4j property graph
                 source of truth              derived network model
```

### Main runtime modes

1. **Web development:** Vite serves the React application, normally on `http://localhost:5173`.
2. **Backend development:** Uvicorn serves FastAPI, normally on `http://localhost:8000`.
3. **Desktop application:** Electron loads the built frontend and packages it as a Windows portable application.
4. **Demo/offline mode:** If the backend is unavailable or the user is not authenticated, the frontend keeps working with deterministic mock data instead of showing an empty UI.

## 3. Repository Layout

```text
SECRET_/
├── src/                         React frontend
│   ├── App.tsx                  section selection and backend connection
│   ├── main.tsx                 React bootstrap and map data exposure
│   ├── pages/                   application screens
│   ├── components/              reusable UI, maps, graph, HUD components
│   ├── services/                typed API client and case selection
│   ├── store/                   Zustand stores, including map/backend state
│   ├── data/                    deterministic mock and local map data
│   ├── types.ts                 shared frontend domain types
│   └── styles.css               HUD design system and map controls
├── electron/
│   ├── main.ts                  Electron main process
│   └── preload.ts               isolated renderer bridge
├── backend/
│   ├── app/                     FastAPI application
│   │   ├── api/v1/              HTTP routers
│   │   ├── models/              domain and ORM models
│   │   ├── repositories/        PostgreSQL data access
│   │   ├── services/             business workflows
│   │   ├── intelligence/         graph and analytical algorithms
│   │   ├── ingestion/             file parsing and normalization
│   │   ├── graph/                 Neo4j/memory graph stores
│   │   └── reports/               PDF and export generation
│   ├── tests/                   unit and integration tests
│   ├── sql/schema.sql           relational schema reference
│   ├── cypher/schema.cypher    graph constraints and schema
│   ├── alembic/                 database migrations
│   └── docker-compose.yml       PostgreSQL and Neo4j services
├── public/textures/             Three.js globe/ambient textures
├── SECRET_Operation_Nightfall_Test_Case/
│                                sample CSV, TXT, JSON case package
├── package.json                 frontend/Electron dependencies and scripts
├── vite.config.ts               Vite configuration
└── PROJECT_OVERVIEW.md          this document
```

## 4. Frontend Technical Approach

### 4.1 Application shell and navigation

`src/App.tsx` owns the active `Section` and maps it to the existing page components. The page is wrapped in `Layout` after login. `ErrorBoundary` prevents a failed visualization from taking down the rest of the application.

The current sections are:

- Command Center
- Investigations
- Case Intake
- Network Intelligence
- Entities
- Timeline
- Locations
- Transactions
- Communications
- Alerts
- Reports
- Settings
- Assistant
- Simulation
- Audit

The UI is intentionally preserved as a HUD/operations dashboard rather than being replaced by a generic CRUD layout.

### 4.2 State management

Zustand is used for lightweight application state:

- `src/store.ts`: login state, active section, selected case and shared application state.
- `src/store/mapStore.ts`: map markers, selected case/location, route visibility, label visibility, and map camera commands.
- `src/store/backend.ts`: backend connection mode, graph data, connection status, and fallback handling.

The frontend does not recreate the MapLibre instance on normal React renders. The map is created once inside `InvestigationMap` and receives data updates through MapLibre sources and layer visibility changes.

### 4.3 API client and fallback behavior

`src/services/api.ts` is a typed `fetch` wrapper. It:

- reads the backend base URL from `VITE_API_URL`;
- defaults to `http://localhost:8000`;
- stores the access token in `localStorage` under `secret.access_token`;
- attaches `Authorization: Bearer <token>` when present;
- converts network and HTTP failures into `ApiError` values;
- exposes typed functions for authentication, graph, cases, entities, sources, analysis, intelligence, alerts, leads, audit, and reports.

`src/store/backend.ts` first attempts to load the graph from the backend. If authentication is missing or the request fails, the store switches to mock mode and uses `src/data/graphMock.ts`. This makes the UI demonstrable without requiring a live database for every frontend session.

### 4.4 Map implementation

`src/components/InvestigationMap.tsx` is the existing map component and is implemented with:

- MapLibre GL JS;
- OpenFreeMap's MapLibre-compatible style and vector tiles;
- actual building footprint/height properties when supplied by the source;
- MapLibre fill-extrusion layers for 3D buildings;
- MapLibre GeoJSON sources for case markers, location markers, and routes;
- MapLibre navigation, scale, pitch, and orbit controls;
- Three.js custom layer for the selected intelligence target overlay.

The map supports pan, scroll/touch zoom, drag rotation, pitch/tilt, reset, fit-all, fit-case, search targeting, route toggling, label toggling, and selected-location camera transitions.

The visual style is applied at the MapLibre style/layer level. It uses a dark blue/black palette, muted land and grass layers, blue roads, dark waterways, restrained labels, real building heights, height-based building colors, and low-contrast route lines. No Mapbox token or Mapbox implementation is required.

The camera approach uses the supported MapLibre camera APIs. Zoom changes are synchronized with a cinematic pitch curve. Selection and orbit use target-relative camera calculations and smooth `easeTo`/`flyTo` transitions. The installed MapLibre version does not expose the public `getFreeCameraOptions`/`setFreeCameraOptions` API, so the implementation avoids private internals and uses the supported equivalent APIs instead.

### 4.5 Graph and analytical visualizations

- `NetworkGraph.tsx` renders relationship networks with React Flow.
- D3 and Recharts support charts and analytical views.
- Three.js and `@react-three/fiber` support ambient 3D elements and custom visualization layers.
- `src/components/geoLayers.ts` and `src/components/terrain.ts` provide reusable 3D/geo helpers.

## 5. Backend Technical Approach

### 5.1 FastAPI entrypoint

`backend/app/main.py` creates the FastAPI application, registers CORS, mounts the versioned router at `/api/v1`, exposes `/health`, and manages startup/shutdown lifecycle for the SQLAlchemy engine and Neo4j connection.

In development/demo mode, startup attempts to seed an admin user without blocking the API if the database is not available.

### 5.2 Layering

```text
HTTP request
    -> API router and dependency/auth checks
    -> service orchestration and domain rules
    -> repository or graph-store access
    -> PostgreSQL / Neo4j / deterministic in-memory store
    -> Pydantic response model
```

Responsibilities are deliberately separated:

- **API routers:** HTTP paths, validation, status codes, authentication dependencies, serialization.
- **Services:** use cases such as case intake, graph materialization, analysis, alert generation, and report creation.
- **Repositories:** relational persistence through SQLAlchemy.
- **Graph stores:** Neo4j implementation plus a memory implementation for tests/offline behavior.
- **Models/schemas:** domain objects, ORM entities, and typed request/response contracts.
- **Intelligence modules:** explainable indicators such as anomalies, communities, priority, temporal patterns, information gain, potential links, and simulation.
- **Reports:** PDF output and investigation exports.

### 5.3 API groups

The versioned API is mounted below `/api/v1`:

| Group | Responsibilities |
|---|---|
| `/health` | service, database, and graph connectivity checks |
| `/auth` | login, refresh, current-user lookup |
| `/dashboard` | command-center summary counters and indicators |
| `/cases` | case CRUD, archive, case sources, case data, alerts, leads, intelligence, simulation |
| `/criminals` | criminal/entity listing and management |
| `/search` | global search across cases, entities, and sources |
| `/graph` | network, entity neighborhood, materialization, graph analytics |
| `/analysis` | assistant, investigation, temporal location, simulation workflows |
| `/reports` | report generation and report retrieval |
| `/audit` | audit event listing and creation |
| `/cases/{case_key}/sources` | upload, parse, process, deduplicate, and delete source files |

FastAPI also generates interactive API documentation at `/docs` and an OpenAPI schema.

## 6. End-to-End Data Flow

### 6.1 Intake and persistence flow

```text
CSV / JSON / TXT / XLSX source file
        |
        v
Upload source to a case
        |
        v
Parser + adapter + normalization
        |
        +--> quality metrics and duplicate/hash checks
        |
        v
Entity and relationship extraction
        |
        v
PostgreSQL records with provenance
        |
        v
Neo4j graph materialization
        |
        v
Analytics, alerts, leads, dashboards, reports
```

The sample `SECRET_Operation_Nightfall_Test_Case` package demonstrates the supported source types with vehicle, transaction, surveillance, location, FIR, CDR, and case files.

### 6.2 Read path

```text
User action in a page
        -> typed frontend API function
        -> FastAPI route
        -> service
        -> repository / graph store
        -> typed JSON response
        -> Zustand/page state
        -> table, graph, chart, map, alert, or report UI
```

### 6.3 Graph analytics path

```text
Neo4j or memory graph snapshot
        -> graph service
        -> centrality/community/bridge/link/risk calculations
        -> indicator with confidence and provenance
        -> Network Intelligence and case intelligence UI
```

The graph is derived for traversal and analytics. PostgreSQL remains the authoritative relational source for case records, source metadata, audit records, and normalized entities.

## 7. Persistence and Data Ownership

### PostgreSQL

PostgreSQL stores normalized application records, including users, cases, criminal/entity records, source metadata, provenance, audit records, alerts, leads, and case analytics data. Alembic owns migrations; `backend/sql/schema.sql` is the reference DDL.

### Neo4j

Neo4j stores entity nodes and typed relationship edges for network traversal and graph algorithms. Constraints and graph shape are documented in `backend/cypher/schema.cypher` and `backend/GRAPH-SCHEMA.md`.

### In-memory graph store

The memory graph implementation makes unit tests and demo operation resilient when Neo4j is unavailable. The resilient graph-store factory can use the configured Neo4j store in production-like operation and fall back when appropriate.

## 8. Configuration and Secrets

Frontend configuration:

```env
VITE_API_URL=http://localhost:8000
```

Backend configuration is defined by `backend/.env.example`:

```env
DATABASE_URL=postgresql+asyncpg://secret:secret@localhost:5432/secret
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=secret
JWT_SECRET=change-me-to-a-long-random-string
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
SECRET_ENV=dev
CORS_ORIGINS=["http://localhost:5173"]
```

Rules:

- Copy `.env.example` files to local `.env` files where required.
- Never commit real database passwords, JWT secrets, tokens, or credentials.
- Use a long random JWT secret outside local demo mode.
- Restrict `CORS_ORIGINS` to known frontend origins in deployed environments.
- The current OpenFreeMap map style does not require a Mapbox token. If the map provider changes later, provider credentials must be added through environment configuration rather than source code.

## 9. Local Development

### Frontend only

```powershell
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:5173`.

### Backend API

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Useful endpoints:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`
- `http://localhost:8000/api/v1/health/db`
- `http://localhost:8000/api/v1/health/graph`

### Databases with Docker

```powershell
cd backend
docker compose up -d postgres neo4j
python -m alembic upgrade head
```

Default local development ports are PostgreSQL `5432`, Neo4j browser `7474`, and Neo4j Bolt `7687`.

### Full desktop build

```powershell
npm.cmd run build:web
npm.cmd run build:electron
npm.cmd run build
```

The Electron builder is configured for a Windows portable target and writes output under `release-fresh/`.

## 10. Testing and Verification

Frontend checks:

```powershell
npm.cmd run build:web
```

This runs Vite production compilation and catches TypeScript/build-time integration issues used by the current project workflow.

Backend checks:

```powershell
cd backend
pytest
```

Integration tests requiring PostgreSQL and Neo4j are marked separately and are skipped automatically when external services are unavailable. Unit tests use SQLite and an in-memory graph store where possible, keeping the default test run deterministic.

Recommended manual smoke test:

1. Start the backend and frontend.
2. Open the app and complete the login/demo entry flow.
3. Confirm dashboard sections render even if backend connectivity is disabled.
4. With backend running, confirm login, graph loading, case selection, search, source upload, and case analytics.
5. On Command Center, verify MapLibre pan, zoom, rotation, pitch, reset, fit-all, fit-case, search targeting, markers, routes, labels, and 3D building extrusion.
6. Open `/docs` and verify the OpenAPI document is generated.
7. Run the frontend build and backend tests before packaging.

## 11. Performance Approach

- Keep one MapLibre instance per mounted map component.
- Update GeoJSON sources instead of rebuilding the map or recreating layers.
- Use layer visibility for toggles instead of React-driven DOM marker trees where possible.
- Use real vector-tile building data and minimum zoom thresholds so large-scale views do not render detailed building geometry unnecessarily.
- Keep device/case markers in a small application-owned GeoJSON source.
- Avoid unnecessary graph refreshes and preserve the last usable graph when a refresh fails.
- Use vectorized/persisted graph operations where available and cap network responses through API limits.
- Dispose MapLibre, Three.js, event listeners, and database/Neo4j resources on teardown.

## 12. Security and Governance Approach

- Authentication uses JWT access/refresh tokens through the FastAPI auth routes.
- Passwords and access control belong in backend services; the frontend token is only a client credential, not an authorization boundary.
- CORS is explicitly configured.
- Audit events record meaningful actions.
- Source provenance and confidence are preserved through extracted entities, relationships, and analytical indicators.
- Analytics are presented as explainable indicators, not definitive accusations.
- Sample data is synthetic and should not be replaced with real sensitive data without a formal security, privacy, retention, and access-control review.

## 13. Current Technical Trade-offs and Limitations

1. The frontend can run in mock mode, which is useful for demos but can conceal backend connectivity problems unless the connection indicator/error state is checked.
2. Neo4j and PostgreSQL are separate stores, so graph materialization must be rerun after relevant relational changes.
3. Map buildings depend on the currently configured OpenFreeMap vector source. Where height attributes are missing, the map does not invent random heights.
4. The current MapLibre package does not expose the public FreeCamera getter/setter used by some advanced camera examples. The implementation therefore uses supported target-relative camera calculations and smooth MapLibre transitions.
5. The frontend production bundle contains a large visualization dependency set, so chunking or route-level lazy loading may be useful as the application grows.
6. The existing frontend UI is intentionally treated as a stable/frozen surface; new backend capabilities should be wired behind existing screens before redesigning the shell.

## 14. Recommended Extension Pattern

For a new feature, follow this order:

1. Define or update the backend Pydantic contract and persistence model.
2. Add repository methods for database access.
3. Add a service method containing business rules and provenance handling.
4. Add a versioned FastAPI route with auth and validation.
5. Add a typed function/interface in `src/services/api.ts`.
6. Connect the result to the appropriate Zustand store or page hook.
7. Preserve existing HUD components and add only the minimum UI surface needed.
8. Add backend unit tests and, when applicable, integration tests.
9. Run frontend build, backend tests, and a manual smoke check.

This keeps the system's key boundaries intact: the UI remains replaceable, the API remains typed, PostgreSQL remains authoritative, Neo4j remains analytical, and every intelligence output remains traceable to source data.

## 15. Important Files by Responsibility

| Area | Files |
|---|---|
| Frontend bootstrap | `src/main.tsx`, `src/App.tsx` |
| Global frontend state | `src/store.ts`, `src/store/mapStore.ts`, `src/store/backend.ts` |
| API client | `src/services/api.ts` |
| Command map | `src/components/InvestigationMap.tsx` |
| Graph UI | `src/components/NetworkGraph.tsx` |
| Frontend styling | `src/styles.css` |
| Backend entrypoint | `backend/app/main.py` |
| API registration | `backend/app/api/v1/router.py` |
| Domain services | `backend/app/services/` |
| Relational access | `backend/app/repositories/`, `backend/app/models/` |
| Graph access | `backend/app/graph/`, `backend/app/services/graph_service.py` |
| Ingestion | `backend/app/ingestion/` |
| Intelligence | `backend/app/intelligence/`, `backend/app/services/case_intelligence_service.py` |
| Reports | `backend/app/reports/` |
| Database schema | `backend/sql/schema.sql`, `backend/cypher/schema.cypher` |
| Local infrastructure | `backend/docker-compose.yml`, `backend/DEPLOYMENT.md` |
| Tests | `backend/tests/` |

