"""PostgreSQL real concurrency integration test (Phase 3).

REQUIRES a reachable PostgreSQL matching the configured DATABASE_URL. This file
is marked `integration`; the repo's conftest SKIPS it automatically in
SECRET_ENV=test mode and whenever PostgreSQL is unreachable.

How to run:
    cd backend
    docker compose up -d postgres          # or your local PostgreSQL
    set SECRET_ENV=dev
    python -m alembic upgrade head
    python -m pytest tests/test_integrity_pg.py -m integration

The test uses `pg_try_advisory_xact_lock` (a NON-blocking probe) so it is fully
deterministic: a lock already held by another open session returns False, and
the same key becomes available again as soon as the holder commits. This
directly proves:
  - same case serializes (two sessions cannot hold the same key)
  - different cases use different keys (no unnecessary blocking)
  - the lock releases on commit
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.blockchain.locking import case_lock_key


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pg_advisory_lock_case_scoping_and_release() -> None:
    from app.core.config import get_settings

    url = get_settings().database_url
    if not url.startswith("postgresql") or "sqlite" in url or ":memory:" in url:
        pytest.skip("integration requires a configured PostgreSQL URL")

    engine = create_async_engine(url)
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        key_a = case_lock_key("CASE-TEST-A")
        key_b = case_lock_key("CASE-TEST-B")
        assert key_a != key_b

        async with Maker() as conn_a:
            async with Maker() as conn_b:
                # Session A acquires the Case-A key.
                held = (await conn_a.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key_a})).scalar()
                assert held is True

                # Session B CANNOT acquire the same Case-A key while A holds it.
                blocked = (await conn_b.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key_a})).scalar()
                assert blocked is False

                # Session B CAN acquire the Case-B key immediately (independence).
                other = (await conn_b.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key_b})).scalar()
                assert other is True

                # Commit A -> its key is released.
                await conn_a.commit()

                # Session B can now acquire the Case-A key (lock released on commit).
                freed = (await conn_b.execute(
                    text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key_a})).scalar()
                assert freed is True

                # Roll back B's transaction -> its locks release too.
                await conn_b.rollback()
    finally:
        await engine.dispose()