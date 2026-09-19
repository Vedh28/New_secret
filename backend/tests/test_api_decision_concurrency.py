"""API-level analyst-decision concurrency test.

Two independent authenticated analysts (separate sessions) POST the SAME pair
concurrently through the real FastAPI router/service/repository path. The
database-atomic upsert must yield exactly one authoritative decision row with
canonical entity ordering and no surfaced IntegrityError.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_graph_store, get_db_session
from app.blockchain.isolated import set_integrity_session_factory
from app.core.database import Base
from app.core.security import hash_password
from app.graph.memory_store import MemoryGraphStore
from app.main import app as fastapi_app
from app.models.user import User, UserRole
from app.repositories.link_decision_repository import LinkDecisionRepository


@pytest.fixture()
async def api_decision_ctx(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with maker() as session:
        session.add_all([
            User(username="admin", email="admin@test.local",
                 password_hash=hash_password("admin-secret"), role=UserRole.ADMIN.value),
            User(username="analyst1", email="a1@test.local",
                 password_hash=hash_password("a1-secret"), role=UserRole.ANALYST.value),
        ])
        await session.commit()

    async def _override_db():
        async with maker() as session:
            yield session

    store = MemoryGraphStore()
    set_integrity_session_factory(maker)
    fastapi_app.dependency_overrides[get_db_session] = _override_db
    fastapi_app.dependency_overrides[get_graph_store] = lambda: store

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with maker() as session:
            repo = LinkDecisionRepository(session)
            yield {"client": client, "maker": maker, "engine": engine, "repo": repo}

    fastapi_app.dependency_overrides.clear()
    set_integrity_session_factory(None)
    await engine.dispose()


async def _login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_case(client: httpx.AsyncClient, auth: dict) -> str:
    r = await client.post("/api/v1/cases", json={"title": "Decision Case", "priority": "HIGH"},
                          headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["case_number"]


async def _case_id(maker, case_number: str) -> int:
    from app.repositories.case_repository import CaseRepository
    async with maker() as session:
        case = await CaseRepository(session).get_by_case_number(case_number)
        assert case is not None
        return case.id


class TestApiDecisionConcurrency:
    async def test_concurrent_identical_decision_single_row(self, api_decision_ctx):
        client = api_decision_ctx["client"]
        maker = api_decision_ctx["maker"]

        auth_a = await _login(client, "admin", "admin-secret")
        auth_b = await _login(client, "analyst1", "a1-secret")
        case_number = await _create_case(client, auth_a)
        case_id = await _case_id(maker, case_number)

        async def _post(headers, source, target):
            return await client.post(
                f"/api/v1/cases/{case_number}/potential-links/decision",
                json={"source": source, "target": target, "decision": "CONFIRM",
                      "evidence_ids": ["E1"], "notes": "same pair"},
                headers=headers,
            )

        # True simultaneous execution through the real API path, reversed
        # entity ordering between the two analysts to prove canonicalization.
        responses = await asyncio.gather(
            _post(auth_a, "P-100", "P-200"),
            _post(auth_b, "P-200", "P-100"),
        )

        for r in responses:
            assert r.status_code == 200, r.text

        # Exactly one authoritative row with canonical ordering.
        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.entity_a == "P-100" and row.entity_b == "P-200"
            assert row.new_status == "ANALYST_CONFIRMED"
            assert row.decision == "CONFIRM"

            # Two audit entries (one per analyst request).
            from sqlalchemy import select
            from app.models.audit import AuditLog
            audits = (await session.execute(
                select(AuditLog.action))).scalars().all()
            assert len([a for a in audits if a == "potential_link_confirm"]) == 2

        # Repeated execution remains safe (still one row).
        again = await asyncio.gather(
            _post(auth_a, "P-100", "P-200"),
            _post(auth_b, "P-100", "P-200"),
        )
        for r in again:
            assert r.status_code == 200, r.text
        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1
            assert rows[0].new_status == "ANALYST_CONFIRMED"

    async def test_concurrent_decision_endpoint_returns_valid_state(self, api_decision_ctx):
        client = api_decision_ctx["client"]
        maker = api_decision_ctx["maker"]
        auth = await _login(client, "admin", "admin-secret")
        case_number = await _create_case(client, auth)
        case_id = await _case_id(maker, case_number)

        async def _post():
            return await client.post(
                f"/api/v1/cases/{case_number}/potential-links/decision",
                json={"source": "P-300", "target": "P-400", "decision": "DEFER"},
                headers=auth)

        responses = await asyncio.gather(_post(), _post(), _post())
        for r in responses:
            body = r.json()
            assert r.status_code == 200
            assert body["new_status"] == "DEFERRED"
            assert body["previous_status"] == "POTENTIAL" or body["previous_status"] == "DEFERRED"

        rows = []
        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1
            assert rows[0].new_status == "DEFERRED"