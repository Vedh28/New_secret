"""pytest configuration for SECRET backend."""
import os

# Test mode: the app-level lifespan skips seeding + engine disposal (avoiding
# Windows proactor teardown races). Integration markers are always skipped in
# test mode — unit runs must never depend on live PostgreSQL/Neo4j.
os.environ.setdefault("SECRET_ENV", "test")

import pytest
from fastapi.testclient import TestClient

# Ensure app is importable regardless of CWD.
os.environ.setdefault("PYTHONPATH", ".")

from app.core.dbcheck import check_database_connection  # noqa: E402
from app.core.graphcheck import check_graph_connection  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Return a TestClient bound to the FastAPI app (lifespan runs).

    Used for non-DB tests (health, bootstrap). The lifespan attempts a best-effort
    seed against the configured engine but fails silently if the DB is down.
    """
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_client() -> TestClient:
    """Return a TestClient whose DB sessions point at a fresh SQLite database.

    Creates tables (via ORM metadata) and seeds the default admin user, enabling
    auth and repository tests to run without PostgreSQL/Neo4j/Docker.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.deps import get_graph_store
    from app.core.database import Base, get_db_session
    from app.graph.memory_store import MemoryGraphStore
    from app.main import create_app
    from app.services.seed_service import ensure_admin_user

    async def _setup():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        TestSession = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with TestSession() as session:
            await ensure_admin_user(session)
        return engine, TestSession

    engine, test_session = asyncio.run(_setup())

    async def override_session():
        async with test_session() as session:
            yield session

    from app.main import app as _app

    memory_store = MemoryGraphStore()
    _app.dependency_overrides[get_db_session] = override_session
    _app.dependency_overrides[get_graph_store] = lambda: memory_store
    with TestClient(_app) as test_client:
        yield test_client
    _app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: requires PostgreSQL AND Neo4j (legacy generic)",
    )
    config.addinivalue_line(
        "markers",
        "integration_pg: requires PostgreSQL only",
    )
    config.addinivalue_line(
        "markers",
        "integration_neo4j: requires Neo4j only",
    )
    config.addinivalue_line(
        "markers",
        "integration_full: requires PostgreSQL and Neo4j (full stack)",
    )


def _requires(item) -> set[str]:
    """Return the set of external services a test item depends on."""
    marker = item.get_closest_marker
    if marker("integration_pg") is not None:
        return {"pg"}
    if marker("integration_neo4j") is not None:
        return {"neo4j"}
    if marker("integration_full") is not None:
        return {"pg", "neo4j"}
    if marker("integration") is not None:
        return {"pg", "neo4j"}
    return set()


def _is_integration(item) -> bool:
    return bool(_requires(item))


async def _probe_pg() -> bool:
    try:
        return (await check_database_connection()).get("status") == "ok"
    except Exception:  # noqa: BLE001 - probe failure == unavailable
        return False


async def _probe_neo4j() -> bool:
    try:
        return (await check_graph_connection()).get("status") == "ok"
    except Exception:  # noqa: BLE001 - probe failure == unavailable
        return False


def pytest_collection_modifyitems(session, config, items) -> None:  # type: ignore[no-untyped-def]
    """Gate integration tests per dependency, never globally.

    Unit runs (SECRET_ENV=test) skip ALL integration markers deterministically.
    Outside test mode each service is probed INDEPENDENTLY, so PostgreSQL
    integration tests run when only PostgreSQL is available, and Neo4j tests
    need only Neo4j. Collection never opens external connections unless at least
    one integration test was collected.
    """
    import asyncio

    integration_items = [item for item in items if _is_integration(item)]

    if os.environ.get("SECRET_ENV") == "test":
        for item in integration_items:
            item.add_marker(
                pytest.mark.skip(reason="integration disabled under SECRET_ENV=test")
            )
        return

    if not integration_items:
        return  # no integration tests -> never probe external services

    pg_ok = asyncio.run(_probe_pg())
    neo4j_ok = asyncio.run(_probe_neo4j())
    available = {name for name, ok in (("pg", pg_ok), ("neo4j", neo4j_ok)) if ok}

    for item in integration_items:
        missing = _requires(item) - available
        if missing:
            item.add_marker(
                pytest.mark.skip(
                    reason=f"external service(s) unavailable: {', '.join(sorted(missing))}"
                )
            )
