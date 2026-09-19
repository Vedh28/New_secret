# SECRET — Architecture

**Strategic Entity & Criminal Relationship Exploration Tool**

> Law-enforcement investigative intelligence platform that analyzes criminal network data using Graph AI.
>
> **Phase 1 — Requirement Analysis, Architecture, Folder Structure, Database & Graph Schema.**

---

## 1. Purpose

SECRET helps law-enforcement investigators analyze criminal networks by turning fragmented
records (FIRs, CDRs, transactions, surveillance) into:

- Entities (criminals, organizations, phones, vehicles, locations, accounts)
- Relationship graphs with typed edges
- Community (gang) detection
- Kingpin identification
- Hidden link prediction
- Risk scoring
- Investigation dashboards
- Report generation

**Design constraints**
- All analytics are **indicators**, never a declaration of guilt.
- The system is a decision-support tool; the analyst retains judgment.
- All data is **synthetic / fictional** — never real personal or criminal data.

---

## 2. Existing Frontend Asset (FROZEN)

The frontend already exists and its design is complete. It is **not** to be redesigned.

| Frontend fact | Value |
|---|---|
| Framework | React 19 + TypeScript + Vite |
| Styling | Tailwind CSS (custom "HUD" design system) |
| State | Zustand (`src/store.ts`) |
| Graph viz | React Flow (`reactflow`) |
| Charts | Recharts, D3 |
| 3D | Three.js / react-three-fiber (ambient GlobeScene) |
| Desktop | Electron (win portable `SECRET.exe`) |
| Auth (UI) | Mock entry screen only |

### Frontend navigation sections (source of truth for API surface)

| # | Section ID | Label |
|---|---|---|
| 1 | `command-center` | Command Center |
| 2 | `investigations` | Investigations |
| 3 | `network` | Network Intelligence |
| 4 | `entities` | Entities |
| 5 | `timeline` | Timeline |
| 6 | `locations` | Locations |
| 7 | `transactions` | Transactions |
| 8 | `communications` | Communications |
| 9 | `alerts` | Alerts |
| 10 | `reports` | Reports |
| 11 | `settings` | Settings |

The backend API must map 1:1 onto these surfaces so the frozen UI can be wired to real
data without any visual change.

---

## 3. Tech Stack

### Backend
- **FastAPI** (Python 3.11+) — REST API, OpenAPI/Swagger auto-docs
- **SQLAlchemy 2.0** — PostgreSQL ORM, async
- **Alembic** — migrations
- **PyJWT** — authentication
- **Pydantic v2** — validation / schemas
- **Neo4j Python Driver** — graph queries
- **NetworkX** — prototype graph algorithms (later phases)
- **Scikit-learn** — clustering, anomaly isolation
- **PyTorch** — (optional/flag-gated) deep link-prediction models
- **Pandas** — data frames over synthetic records

### Databases
| Database | Role |
|---|---|
| **PostgreSQL** | Relational source-of-truth: users, criminal profiles, cases, evidence, FIRs, audit |
| **Neo4j** | Property graph: entity nodes + typed relationship edges, gang networks |

### Infrastructure
- **Docker Compose** — Postgres + Neo4j for local dev
- **dotenv** — configuration

---

## 4. High-Level Architecture

```
┌─────────────────────────────────────────────┐
│                 Frontend (React)            │
│   Command Center · Investigations · ...     │
│   Network Intel · Entities · Reports        │
│           (EXISTING UI, FROZEN)             │
└───────────────────┬─────────────────────────┘
                    │  HTTPS / JSON
                    ▼
┌─────────────────────────────────────────────┐
│                FastAPI Backend              │
│  ┌───────────────────────────────────────┐  │
│  │ Router layer (api/v1)                │  │
│  │  auth · criminal · case · graph      │  │
│  │  analytics · reports · audit         │  │
│  └───────────────────┬───────────────────┘  │
│                      ▼                      │
│  ┌───────────────────────────────────────┐  │
│  │ Service layer (business logic)        │  │
│  │  CriminalService · CaseService        │  │
│  │  GraphService  · AnalyticsService     │  │
│  │  AuthService   · ReportService        │  │
│  └──────────┬───────────────┬────────────┘  │
│             │               │               │
│             ▼               ▼               │
│  ┌───────────────┐   ┌───────────────┐      │
│  │ PostgreSQL    │   │  Neo4j        │      │
│  │ (relational)  │   │  (graph)      │      │
│  └───────────────┘   └───────────────┘      │
└─────────────────────────────────────────────┘
```

### Layer responsibilities

| Layer | Responsibility |
|---|---|
| **API / Router** | HTTP contract, auth guard, request validation, serialization |
| **Service** | Orchestrate business rules, call repositories & external libs |
| **Repository** | Data access (SQLAlchemy sessions / Neo4j driver) |
| **Model** | Domain types (SQLAlchemy models + Pydantic schemas) |
| **Analytics / ML** | Graph algorithms, community detection, risk scoring (later phases) |
| **Ingestion** | Parse synthetic source records; later real adapters (FIR, CDR, ...) |

---

## 5. Proposed Folder Structure (Backend)

```
backend/
├── ARCHITECTURE.md
├── DATABASE.md
├── GRAPH-SCHEMA.md
├── README.md
├── requirements.txt
├── .env.example
├── docker-compose.yml
│
├── sql/
│   └── schema.sql            # PostgreSQL DDL
│
├── cypher/
│   ├── schema.cypher         # Node/relationship + constraints
│   └── seed.cypher           # Synthetic seed graph (sample)
│
└── app/
    ├── __init__.py
    ├── main.py               # FastAPI app factory + router registration
    ├── core/
    │   ├── __init__.py
    │   ├── config.py         # pydantic-settings / env
    │   ├── security.py       # JWT encode/decode, password hashing
    │   ├── database.py       # SQLAlchemy engine/session (async)
    │   └── neo4j.py          # Neo4j driver singleton
    ├── models/               # SQLAlchemy ORM models
    │   ├── __init__.py
    │   ├── user.py
    │   ├── criminal.py
    │   ├── case.py
    │   ├── evidence.py
    │   └── fir.py
    ├── schemas/              # Pydantic request/response
    │   ├── __init__.py
    │   ├── auth.py
    │   ├── criminal.py
    │   ├── case.py
    │   └── common.py
    ├── api/                  # V1 routers
    │   ├── __init__.py
    │   ├── deps.py           # Depends(current_user), db session
    │   └── v1/
    │       ├── __init__.py
    │       ├── router.py     # aggregator
    │       ├── auth.py
    │       ├── criminals.py
    │       ├── cases.py
    │       └── graph.py
    ├── services/             # business logic
    │   ├── __init__.py
    │   ├── auth_service.py
    │   ├── criminal_service.py
    │   ├── case_service.py
    │   └── graph_service.py
    ├── repositories/         # data access
    │   ├── __init__.py
    │   └── base.py
    └── utils/
        ├── __init__.py
        └── ids.py            # entity id helpers (P-, O-, V-, ...)
```

> `analytics/`, `ml/`, and `ingestion/` are **reserved** for later phases (AI modules implemented in Phase 8). They are intentionally not scaffolded yet.

---

## 6. Data Flow

### Write path (records → graph)
```
Synthetic source record (FIR/CDR/tx)
        │
        ▼
IngestionService (Phase 3/4)
        │  normalize + extract entities/relationships
        ▼
Relational persistence (PostgreSQL)
        │
        ▼
Graph materialization (Neo4j)
        │
        ▼
Analytics cache / indices
```

### Read path (UI → data)
```
Frontend section  ──►  GET /api/v1/{resource}  ──►  Service  ──►  Postgres / Neo4j
       ▲                                                        │
       └──────────────  typed JSON response ◄───────────────────┘
```

### Analytic path (Network Intelligence)
```
Graph query (Neo4j / NetworkX snapshot)
        │
        ▼
AnalyticsService: centrality · community · bridge · risk
        │
        ▼
Insights + provenance (source_ids + confidence) → UI
```

---

## 7. API Surface (planned, by section)

| Section (UI) | Proposed route group |
|---|---|
| Auth / Login | `POST /api/v1/auth/login` · `POST /api/v1/auth/refresh` |
| Command Center | `GET /api/v1/dashboard/summary` |
| Investigations | `POST/GET /api/v1/cases` · `GET /api/v1/cases/{id}` |
| Network Intelligence | `GET /api/v1/graph/network` · `GET /api/v1/analytics/...` |
| Entities | `GET /api/v1/criminals` · `GET /api/v1/criminals/{id}` |
| Timeline | `GET /api/v1/cases/{id}/timeline` |
| Locations | `GET /api/v1/locations` (Phase later) |
| Transactions | `GET /api/v1/transactions` (Phase later) |
| Communications | `GET /api/v1/communications` (Phase later) |
| Alerts | `GET /api/v1/alerts` (Phase later) |
| Reports | `POST /api/v1/reports/generate` |
| Settings | `GET/PATCH /api/v1/settings` (later) |

> Concrete endpoint specs are defined within each phase as it is built.

---

## 8. Key Design Decisions

1. **Frozen UI** — backend is strictly additive; it serves data to the existing screens.
2. **Two data stores with clear ownership:**
   - PostgreSQL = normative relational records, provenance, audit.
   - Neo4j = derived analytical graph for traversal/ML.
3. **Strong typing everywhere** — Pydantic v2 + SQLAlchemy 2 + Python `TypedDict` for graph results.
4. **Provenance-first** — every entity/relationship/insight carries `source_id(s)`, `source_type`, `confidence`, `timestamp`.
5. **Explainable, non-accusatory** — analytics output "high priority indicator / anomaly", never "guilty".
6. **Deterministic synthetic data** — seeded, reproducible demo.
7. **Async** — FastAPI + async SQLAlchemy for concurrency; Neo4j driver is async-capable.
8. **Audit trail** — every meaningful action logged (who/what/when/result).

---

## 9. Environment / Configuration

Keys (see `.env.example`):
```
DATABASE_URL=postgresql+asyncpg://secret:secret@localhost:5432/secret
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=secret
JWT_SECRET=change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
SECRET_ENV=dev
```

---

## 10. Phase Plan (roadmap)

| Phase | Scope |
|---|---|
| **1 (this)** | Architecture, folder layout, DB + graph schema, scaffolding |
| 2 | Backend setup: FastAPI, JWT, Postgres + Neo4j connections |
| 3 | Authentication APIs |
| 4 | Criminal APIs |
| 5 | Case APIs |
| 6 | Relationship / Graph APIs |
| 7 | Network visualization integration (wire existing UI graph) |
| 8 | AI modules (community, kingpin, centrality, link prediction, risk) |
| 9 | Report generation |
| 10 | Deployment |

Each phase is independently verified and confirmed before the next begins.


## Transaction Ownership (Integrity Layer)

### Authoritative business transaction (owns the outcome)
- case / source / evidence / intelligence / analyst decision / report / audit
- Committed FIRST; never depends on integrity success.

### Integrity transaction (best-effort, verifiable, retryable)
- integrity outbox, ledger blocks, ledger events, evidence integrity,
  snapshot integrity, analyst-decision integrity, report integrity
- Runs in a SEPARATE session via `app/blockchain/isolated.run_integrity_isolated`,
  sharing the configured engine; committed or rolled back independently.
- Integrity failure NEVER poisons the business session; it is logged with
  safe context and leaves the outbox PENDING/FAILED for retry.

### Rule
`Business persistence MUST NOT depend on integrity persistence succeeding.`

### Lock lifetime
- PostgreSQL: transaction-scoped `pg_advisory_xact_lock` per case, released on
  the integrity transaction's commit/rollback (or the business commit for the
  small in-transaction enqueue path).
- SQLite (tests/dev only): database/file-wide writer serialization; not
  per-case. Correctness preserved; no per-case parallelism claim.

### Terminology
The local implementation is a PERMISSIONED CHAINED INTEGRITY LEDGER (database
backed) -- not a decentralized public blockchain, and not cryptocurrency.
An institutional deployment may back the same `BlockchainLedger` abstraction
with a permissioned distributed ledger (e.g. Hyperledger Fabric).

## Durable Decision Records (final hardening)

### Provenance stamping is a targeted JSON merge (no lost updates)
`SourceService.process()` persists parsed records + provenance in the
authoritative transaction. Afterwards `_enrich_provenance_isolated()` stamps
the committed ledger references (`integrity_tx`, `integrity_block`,
`merkle_root`) + the per-record provenance entries onto the committed source's
`metadata_json`.

The stamp is a **dialect JSON-merge UPDATE** (`jsonb_set` on PostgreSQL,
`json_set` on SQLite) that rewrites ONLY the provenance / integrity keys in
place. It never reads-and-replaces the whole `metadata_json` document, so an
unrelated metadata key written concurrently by another transaction can never be
silently overwritten. `metadata_json` stays a single source of truth for the
source's own content; ownership of the four integrity keys is partitioned to the
integrity path. (Regression suite: `test_source_provenance_concurrency.py`.)

### Source (re-)processing is content-versioned and idempotent
Re-running `POST /{case}/sources/{source_id}/process` on an UNCHANGED source is
a no-op commit-wise: every ledger event
(`EVIDENCE_PROCESSED` / `RECORD_BATCH_REGISTERED` / `ENTITY_EXTRACTED` /
`RELATIONSHIP_DERIVED`) carries a dedupe key derived from its content (Merkle
root / counts), so re-processing collapses onto the existing outbox rows and
NEVER duplicates ledger events, Merkle commitments or chained blocks.
Reprocessing with CHANGED records produces a new root -> an explicit new
commitment, i.e. version semantics are content-defined. Authoritative entity /
relationship persistence was already idempotent (merge by
(case, identity, type) / (case, type, source, target)).

### Graph projection is derived, synchronously refreshed
PostgreSQL is the source of truth; Neo4j (or the memory store) is a derived
projection. `process_source` materializes the case graph BEFORE committing the
authoritative processing transaction and intentionally aborts the whole
processing commit if the graph refresh fails: the caller sees a clear
500 "rolled back; fix the graph store and retry" instead of a false
"processed successfully" with a diverged projection. No silent divergence is
ever hidden. A ledger/batch failure (which happens AFTER the commit) never
rolls back the authoritative processing result.

### Per-process intelligence cache is invalidated at every mutation
`CaseIntelligenceService` caches per case in-process (`_cache`), so the
following endpoints explicitly call `invalidate_case_cache(case_id)`:
source upload, source register, source process, source delete, and analyst
decision. Case A mutations never touch Case B's entry. The cache is ephemeral
in-memory optimization, not authoritative storage.

### Analyst decision upsert (final)
`LinkDecisionRepository.upsert_pair()` is a database-atomic upsert keyed by
`UNIQUE(case_id, entity_a, entity_b)`. Concurrent requests for the same pair
collapse onto one row; `previous_status` auto-advances from the existing row's
`new_status`. PostgreSQL validation lives in
`test_api_decision_concurrency_pg.py` (CI `backend-integration-pg`); the SQLite
parallel is `test_api_decision_concurrency.py`.

### Session-factory override hygiene
Tests point isolated integrity work at a test engine via
`set_integrity_session_factory`. Every fixture that overrides it restores the
previously installed factory on teardown (even on test failure), and the
production default (`None`) always falls back to `async_session_factory`.
No test installed override can leak into another test or into production.
