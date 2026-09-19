"""Tests for the isolated integrity transaction runner.

`run_integrity_isolated` must always:
  - succeed  -> commit + close, return (True, result, None)
  - builder  -> rollback + close, return (False, None, error), never re-raise
  - commit   -> rollback + close, return (False, None, error)
  - rollback -> still close, return (False, None, error)
and never touch the caller's own session/transaction.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.blockchain.isolated as isolated
from app.core.database import Base


@pytest.fixture()
async def isolated_ctx(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'iso.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Route isolated sessions at the test engine, restoring the default after.
    previous = isolated._integrity_session_factory
    isolated.set_integrity_session_factory(maker)
    yield {"maker": maker, "engine": engine}
    isolated.set_integrity_session_factory(previous)
    await engine.dispose()


async def _run_select(session):
    result = await session.execute(text("SELECT 42 AS answer"))
    return result.scalar()


class TestIsolatedRunner:
    async def test_success_commits_and_closes(self, isolated_ctx):
        ok, result, error = await isolated.run_integrity_isolated(_run_select)
        assert ok is True
        assert result == 42
        assert error is None

    async def test_builder_failure_rolls_back_and_returns_tuple(self, isolated_ctx):
        maker = isolated_ctx["maker"]

        async def _builder(session):
            await session.execute(text("INSERT INTO audit_logs (action, result) VALUES ('x','{}')"))
            await session.flush()
            raise RuntimeError("boom")

        ok, result, error = await isolated.run_integrity_isolated(_builder)
        assert ok is False
        assert result is None
        assert isinstance(error, RuntimeError)

        # The partial write was rolled back.
        async with maker() as session:
            rows = (await session.execute(text("SELECT count(*) FROM audit_logs"))).scalar()
            assert rows == 0

    async def test_commit_failure_rolls_back_and_returns_tuple(self, isolated_ctx, monkeypatch):
        maker = isolated_ctx["maker"]
        session = maker()

        async def _boom_commit():
            raise RuntimeError("commit failed")

        original_make = isolated._make_session
        monkeypatch.setattr(isolated, "_make_session", lambda: session)
        session.commit = _boom_commit  # type: ignore[method-assign]
        try:
            ok, result, error = await isolated.run_integrity_isolated(_run_select)
        finally:
            monkeypatch.undo()
            await session.close()

        assert ok is False
        assert result is None
        assert isinstance(error, RuntimeError)

    async def test_rollback_failure_still_closes_session(self, isolated_ctx, monkeypatch):
        maker = isolated_ctx["maker"]
        session = maker()

        async def _boom_commit():
            raise RuntimeError("commit failed")

        async def _boom_rollback():
            raise RuntimeError("rollback failed")

        monkeypatch.setattr(isolated, "_make_session", lambda: session)
        session.commit = _boom_commit  # type: ignore[method-assign]
        session.rollback = _boom_rollback  # type: ignore[method-assign]
        try:
            # Must NOT raise even though commit AND rollback both fail.
            ok, result, error = await isolated.run_integrity_isolated(_run_select)
            assert ok is False
            assert isinstance(error, RuntimeError)
        finally:
            monkeypatch.undo()
            await session.close()

    async def test_caller_session_is_unaffected(self, isolated_ctx):
        maker = isolated_ctx["maker"]
        # Caller's own authoritative session: write + commit normally BEFORE
        # and AFTER a failing isolated call.
        async with maker() as caller:
            await caller.execute(text("INSERT INTO audit_logs (action, result) VALUES ('a','{}')"))
            await caller.commit()

            async def _failing(session):
                raise RuntimeError("isolated failure")

            ok, _r, _e = await isolated.run_integrity_isolated(_failing)
            assert ok is False

            await caller.execute(text("INSERT INTO audit_logs (action, result) VALUES ('b','{}')"))
            await caller.commit()

        async with maker() as fresh:
            actions = (await fresh.execute(
                text("SELECT action FROM audit_logs ORDER BY id"))).scalars().all()
            assert list(actions) == ["a", "b"]

    async def test_override_falls_back_to_production_factory(self, isolated_ctx):
        """Restoring `None` must route isolated sessions back to the configured
        application factory — a test override can never leak into production."""
        import app.blockchain.isolated as isolated_mod

        assert isolated_mod._integrity_session_factory is isolated_ctx["maker"]
        overridden = isolated_mod._make_session()
        assert overridden.get_bind().dialect.name == "sqlite"
        assert str(overridden.get_bind().url) == str(isolated_ctx["engine"].url)
        await overridden.close()

        # Restore the production default exactly like test teardown does.
        previous = isolated_mod._integrity_session_factory
        isolated_mod.set_integrity_session_factory(None)
        try:
            from app.core.database import async_session_factory
            produced = isolated_mod._make_session()
            bind = produced.get_bind()
            default_bind = async_session_factory().get_bind()
            assert str(bind.url) == str(default_bind.url)
            assert default_bind.dialect.name == "postgresql"  # production engine
            await produced.close()
        finally:
            isolated_mod.set_integrity_session_factory(previous)