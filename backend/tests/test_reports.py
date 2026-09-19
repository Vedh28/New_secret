"""Report tests (Phase 9).

Verifies report generation returns structured content + a PDF artifact, and that
reports can be retrieved, against the SQLite DB + in-memory graph store.
"""
import asyncio
import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_graph_store
from app.core.database import Base, get_db_session
from app.core.security import hash_password
from app.graph.memory_store import MemoryGraphStore
from app.graph.types import GraphEdge, GraphNode
from app.main import app
from app.models.case import Case
from app.models.criminal import CriminalProfile
from app.models.user import User, UserRole

ADMIN = "admin"
PW = "admin-secret"


@pytest.fixture()
def report_client() -> TestClient:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    S = async_sessionmaker(eng, expire_on_commit=False)

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with S() as s:
            s.add(User(username="admin", email="admin@example.com",
                      password_hash=hash_password(PW), role=UserRole.ADMIN.value))
            p = CriminalProfile(secret_id="P-0421", profile_type="PERSON", name="Person A",
                                risk_score=94, risk_level="CRITICAL", confidence=96, aliases=["Alpha"])
            c = Case(case_number="CASE-2026-0001", title="Organized Network Analysis",
                     status="OPEN", priority="HIGH")
            s.add_all([p, c])
            await s.commit()

    asyncio.run(setup())

    store = MemoryGraphStore()
    store.nodes["P-0421"] = GraphNode(id="P-0421", type="PERSON", name="Person A",
                                      properties={"risk_score": 94, "risk_level": "CRITICAL"})
    store.nodes["O-1101"] = GraphNode(id="O-1101", type="ORGANIZATION", name="Org Orion",
                                      properties={"risk_score": 89})
    asyncio.run(store.upsert_edge(GraphEdge(
        id="E1", source_id="P-0421", target_id="O-1101", type="MEMBER_OF",
        properties={"confidence": 0.9})))

    async def override_db():
        async with S() as s:
            yield s

    from app.blockchain.isolated import set_integrity_session_factory
    set_integrity_session_factory(S)
    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_graph_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    set_integrity_session_factory(None)
    asyncio.run(eng.dispose())


def _auth(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_generate_network_report(report_client: TestClient) -> None:
    resp = report_client.post(
        "/api/v1/reports/generate",
        json={"report_type": "network_analysis", "title": "Network Analysis Report"},
        headers=_auth(report_client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["report_type"] == "network_analysis"
    assert body["title"] == "Network Analysis Report"
    assert len(body["sections"]) >= 3
    # Artifact is a base64 PDF.
    pdf = base64.b64decode(body["artifact"])
    assert pdf.startswith(b"%PDF-1.4")


def test_generate_investigation_report(report_client: TestClient) -> None:
    resp = report_client.post(
        "/api/v1/reports/generate",
        json={"report_type": "investigation_summary", "case_number": "CASE-2026-0001"},
        headers=_auth(report_client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    sections = {s["heading"] for s in body["sections"]}
    assert "Case Overview" in sections


def test_generate_entity_report(report_client: TestClient) -> None:
    resp = report_client.post(
        "/api/v1/reports/generate",
        json={"report_type": "entity_intelligence", "entity_id": "P-0421"},
        headers=_auth(report_client),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    sections = {s["heading"] for s in body["sections"]}
    assert "Entity Overview" in sections


def test_generate_report_then_get_by_id(report_client: TestClient) -> None:
    auth = _auth(report_client)
    gen = report_client.post(
        "/api/v1/reports/generate",
        json={"report_type": "network_analysis"},
        headers=auth,
    )
    assert gen.status_code == 201
    report_id = gen.json()["id"]

    get_resp = report_client.get(f"/api/v1/reports/{report_id}", headers=auth)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == report_id


def test_get_missing_report_404(report_client: TestClient) -> None:
    resp = report_client.get("/api/v1/reports/nonexistent", headers=_auth(report_client))
    assert resp.status_code == 404


def test_generate_requires_auth(report_client: TestClient) -> None:
    resp = report_client.post("/api/v1/reports/generate",
                              json={"report_type": "network_analysis"})
    assert resp.status_code == 401
