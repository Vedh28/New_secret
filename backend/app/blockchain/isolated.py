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


async def run_integrity_isolated(builder: Callable[[AsyncSession], Awaitable[T]],
                                 commit: bool = True) -> tuple[bool, T | None, Exception | None]:
    """Run an integrity callable in its own committed transaction.

    Returns (success, result, error). On failure the integrity session is
    rolled back (never left open or half-committed); the caller's own session
    is untouched. `commit=False` leaves the transaction open for the caller to
    finish (rare; used only where the caller must own the commit).
    """
    session = _make_session()
    try:
        result = await builder(session)
        if commit:
            await session.commit()
        return True, result, None
    except Exception as exc:  # noqa: BLE001 - boundary separator; caller logs
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
        logger.warning("isolated integrity transaction failed type=%s: %s",
                       type(exc).__name__, exc)
        return False, None, exc
    finally:
        await session.close()


async def report_integrity_outcome(success: bool, operation: str, case_id, error: Exception | None) -> str:
    """Log an isolated integrity outcome with safe context; return status text."""
    if success:
        return "INTEGRITY_OK"
    logger.warning("integrity %s failed for case=%s type=%s", operation, case_id,
                   type(error).__name__ if error else "unknown")
    return "INTEGRITY_UNAVAILABLE"


# Re-export for convenience at other call sites.
__all__ = ["run_integrity_isolated", "report_integrity_outcome", "AsyncSession", "Any"]