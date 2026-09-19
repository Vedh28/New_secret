"""Isolated integrity transaction boundary (Phase 1 hardening).

Rule: best-effort integrity work must NEVER poison the authoritative business
transaction the way `try: ...; commit()` does when the error left the
SQLAlchemy session in a rollback-required state.

`run_integrity_isolated(builder)` executes an integrity operation on its OWN
AsyncSession (sharing the application's configured engine/session factory), so:

  - business transaction (decision/evidence/intelligence/report) commits
    independently and is NEVER left failed by an integrity error
  - integrity commit/rollback happens in a separate transaction; a failure
    produces (False, None, exc) which the caller logs with safe context
  - the PostgreSQL advisory lock / SQLite write lock acquired inside the
    operation is released by the isolated transaction's commit/rollback
  - no new engine is created per request; the configured factory is reused

This does NOT replace the DB-level concurrency guarantees (advisory locks,
unique constraints) — it only isolates transaction ownership.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import async_session_factory

logger = logging.getLogger("secret.integrity")

T = TypeVar("T")

# Pluggable session factory so TESTS can point isolated integrity work at their
# own (SQLite) engine while production uses the application's configured
# engine. Defaults to the application factory; `set_integrity_session_factory`
# is called by test fixtures that override the DB session.
_integrity_session_factory: async_sessionmaker | None = None


def set_integrity_session_factory(factory: async_sessionmaker | None) -> None:
    """Point isolated integrity sessions at `factory` (or reset to default)."""
    global _integrity_session_factory
    _integrity_session_factory = factory


def _make_session() -> AsyncSession:
    factory = _integrity_session_factory if _integrity_session_factory is not None else async_session_factory
    return factory()


async def run_integrity_isolated(builder: Callable[[AsyncSession], Awaitable[T]]) -> tuple[bool, T | None, Exception | None]:
    """Run an integrity callable in its own committed transaction.

    Returns (success, result, error). On success the integrity session is
    committed and closed; on failure it is rolled back and closed. The caller's
    own session is never touched, so a best-effort integrity failure can never
    poison an authoritative business transaction.
    """
    session = _make_session()
    try:
        result = await builder(session)
        await session.commit()
        return True, result, None
    except Exception as exc:  # noqa: BLE001 - boundary separator; caller logs
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - best-effort cleanup: still close below
            logger.debug("isolated integrity rollback cleanup failed type=%s",
                         type(exc).__name__)
        logger.warning("isolated integrity transaction failed type=%s: %s",
                       type(exc).__name__, exc)
        return False, None, exc
    finally:
        await session.close()


__all__ = ["run_integrity_isolated", "set_integrity_session_factory", "AsyncSession", "Any"]