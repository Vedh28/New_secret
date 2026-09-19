"""REAL PostgreSQL API-level analyst-decision concurrency test (final).

This is the PostgreSQL counterpart of `test_api_decision_concurrency.py`. It
exercises the full application path against a REAL PostgreSQL database:

    HTTP request -> FastAPI router -> auth -> DB dependency -> decision
    endpoint -> LinkDecisionRepository.upsert_pair() -> PostgreSQL

It is gated behind `integration_pg`. The repo's conftest SKIPS it in
SECRET_ENV=test mode and whenever PostgreSQL is unreachable, so it only runs
against a real PG (CI `backend-integration-pg` job applies `alembic upgrade
head`, then runs `pytest -m "integration_pg or integration_full"`).

Run locally (PostgreSQL running):
    set SECRET_ENV=dev
    python -m alembic upgrade head
    python -m pytest tests/test_api_decision_concurrency_pg.py -q
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_db_session, get_graph_store
from app.blockchain.isolated import set_integrity_session_factory
from app.core.config import get_settings
from app.core.database import Base
from app.core.security import hash_password
from app.graph.memory_store import MemoryGraphStore
from app.main import app as fastapi_app
from app.models.user import User, UserRole
from app.repositories.link_decision_repository import LinkDecisionRepository

DECISION_VALUES = {"CONFIRM", "REJECT", "DEFER"}
VALID_STATUSES = {"ANALYST_CONFIRMED", "ANALYST_REJECTED", "DEFERRED"}


@pytest.fixture()
async def pg_ctx():
    url = get_settings().database_url
    if (not url.startswith("postgresql")) or "sqlite" in url or ":memory:" in url:
        pytest.skip("integration requires a configured PostgreSQL URL")
    engine = create_async_engine(url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    # Idempotent: creates any tables a fresh database lacks (CI normally runs
    # `alembic upgrade head` first; create_all only fills the gaps).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Maker() as session:
        session.add_all([
            User(username="admin", email="admin@pg.local",
                 password_hash=hash_password("admin-secret"), role=UserRole.ADMIN.value),
            User(username="analyst1", email="a1@pg.local",
                 password_hash=hash_password("a1-secret"), role=UserRole.ANALYST.value),
            User(username="analyst2", email="a2@pg.local",
                 password_hash=hash_password("a2-secret"), role=UserRole.ANALYST.value),
        ])
        await session.commit()

    async def _override_db():
        async with Maker() as session:
            yield session

    store = MemoryGraphStore()
    set_integrity_session_factory(Maker)
    fastapi_app.dependency_overrides[get_db_session] = _override_db
    fastapi_app.dependency_overrides[get_graph_store] = lambda: store

    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with Maker() as session:
            repo = LinkDecisionRepository(session)
            yield {"client": client, "maker": Maker, "engine": engine, "repo": repo}

    fastapi_app.dependency_overrides.clear()
    set_integrity_session_factory(None)
    await engine.dispose()


async def _login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _create_case(client: httpx.AsyncClient, auth: dict) -> str:
    r = await client.post("/api/v1/cases", json={"title": "PG Decision Case", "priority": "HIGH"},
                          headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["case_number"]


async def _case_id(maker, case_number: str) -> int:
    from app.repositories.case_repository import CaseRepository
    async with maker() as session:
        case = await CaseRepository(session).get_by_case_number(case_number)
        assert case is not None
        return case.id


@pytest.mark.integration_pg
class TestPgApiDecisionConcurrency:
    async def _concurrent_round(self, ctx, case_number, pairs):
        client = ctx["client"]
        results = await asyncio.gather(*[
            client.post(
                f"/api/v1/cases/{case_number}/potential-links/decision",
                json={"source": s, "target": t, "decision": decision,
                      "evidence_ids": [f"E{i}"], "notes": "pg-round"},
                headers=auth,
            )
            for (auth, s, t, decision, i) in pairs
        ])
        for r in results:
            assert r.status_code == 200, r.text
        return results

    async def test_concurrent_reversed_pairs_single_row(self, pg_ctx):
        client, maker = pg_ctx["client"], pg_ctx["maker"]
        auth_a = await _login(client, "admin", "admin-secret")
        auth_b = await _login(client, "analyst1", "a1-secret")
        case_number = await _create_case(client, auth_a)
        case_id = await _case_id(maker, case_number)

        # Two analysts, same logical pair, REVERSED entity ordering, concurrent.
        await self._concurrent_round(pg_ctx, case_number, [
            (auth_a, "P-100", "P-200", "CONFIRM", 1),
            (auth_b, "P-200", "P-100", "CONFIRM", 2),
        ])

        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1  # exactly one authoritative row
            assert rows[0].entity_a == "P-100" and rows[0].entity_b == "P-200"
            assert rows[0].new_status == "ANALYST_CONFIRMED"
            assert rows[0].decision == "CONFIRM"
            assert rows[0].previous_status in ("POTENTIAL", "ANALYST_CONFIRMED")

        # Multiple concurrent repeated rounds stay coherent: one row,
        # canonical ordering, no IntegrityError, no lost state.
        for _ in range(3):
            await self._concurrent_round(pg_ctx, case_number, [
                (auth_a, "P-100", "P-200", "CONFIRM", 1),
                (auth_b, "P-200", "P-100", "CONFIRM", 2),
            ])
        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1
            assert rows[0].entity_a == "P-100" and rows[0].entity_b == "P-200"
            assert rows[0].new_status == "ANALYST_CONFIRMED"

    async def test_concurrent_different_decisions_one_valid_state(self, pg_ctx):
        client, maker = pg_ctx["client"], pg_ctx["maker"]
        auth_a = await _login(client, "analyst1", "a1-secret")
        auth_b = await _login(client, "analyst2", "a2-secret")
        case_number = await _create_case(client, auth_a)
        case_id = await _case_id(maker, case_number)

        # Competing decisions for the SAME pair: the database-atomic upsert must
        # converge to ONE row holding ONE valid committed state. Which analyst
        # "wins" is intentionally NOT asserted.
        pairs = [(auth_a, "P-300", "P-400", "REJECT", 1),
                 (auth_b, "P-400", "P-300", "CONFIRM", 2)]
        for _ in range(5):
            await self._concurrent_round(pg_ctx, case_number,
                                         [pairs[0], pairs[1] if _ % 2 == 0 else pairs[0]])

        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1  # never a duplicate / corrupted pair
            row = rows[0]
            assert row.entity_a == "P-300" and row.entity_b == "P-400"
            assert row.new_status in VALID_STATUSES
            assert row.previous_status in ("POTENTIAL", *VALID_STATUSES)
            assert {row.entity_a, row.entity_b} == {"P-300", "P-400"}

    async def test_many_concurrent_same_pair_no_integrity_error(self, pg_ctx):
        client, maker = pg_ctx["client"], pg_ctx["maker"]
        auth = await _login(client, "admin", "admin-secret")
        case_number = await _create_case(client, auth)
        case_id = await _case_id(maker, case_number)

        await self._concurrent_round(pg_ctx, case_number, [
            (auth, "P-500", "P-600", "DEFER", i) for i in range(8)
        ])
        async with maker() as session:
            rows = await LinkDecisionRepository(session).list_by_case(case_id)
            assert len(rows) == 1
            assert rows[0].new_status == "DEFERRED"