"""Case-scoped flush serialization (Phase 2/3).

POSTGRESQL (production):
    SELECT pg_advisory_xact_lock(:key)   -- transaction-scoped, releases on
    commit/rollback, per-case key derived deterministically (never Python's
    randomized hash()).

SQLITE (tests / non-PG dev):
    advisory locks do not exist, so we serialize the same critical section
    with a dedicated `integrity_flush_locks` row: the INSERT acquires SQLite's
    file-level write lock inside the transaction, which makes a second
    concurrent worker block until the first commits. This is a functional
    emulation — the production guarantee is the PostgreSQL advisory lock.

Both strategies are case-scoped and transaction-scoped; no global lock, no
process-local mutex, no in-memory state.
"""
from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_LOCK_NAMESPACE = b"secret:case-flush:"


def case_lock_key(case_id) -> int:
    """Deterministic signed 64-bit advisory-lock key from a case identifier."""
    if isinstance(case_id, (int, float)):
        case_id = str(int(case_id))
    digest = hashlib.sha256(_LOCK_NAMESPACE + str(case_id).encode("utf-8")).digest()[:8]
    value = int.from_bytes(digest, "big")
    # Map unsigned 64-bit into the signed BIGINT range PostgreSQL accepts.
    return value - (1 << 64) if value >= (1 << 63) else value


@asynccontextmanager
async def acquire_case_flush_lock(session: AsyncSession, case_id) -> AsyncIterator[None]:
    """Serialize flush_pending(case_id) across workers/processes.

    The lock is held by the OPEN transaction and is released only when that
    transaction commits or rolls back (callers must commit after the critical
    section — the existing endpoint/service contract does).
    """
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        key = case_lock_key(case_id)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": key},
        )
    else:
        # SQLite (and other non-PG dialects): acquire the engine's write lock
        # for the transaction via a per-case token row so concurrent flushes of
        # the same case are serialized at the database level, not in Python.
        await session.execute(
            text(
                "INSERT INTO integrity_flush_locks (case_id, holder) "
                "VALUES (:case_id, :holder) "
                "ON CONFLICT (case_id) DO NOTHING"
            ),
            {"case_id": str(int(case_id)) if isinstance(case_id, (int, float)) else str(case_id),
             "holder": "flush"},
        )
    try:
        yield
    except Exception:
        # Transaction (and therefore the lock) rolls back with the failure.
        raise