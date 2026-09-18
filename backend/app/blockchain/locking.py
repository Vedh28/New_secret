"""Case-scoped flush serialization (Phase 2/3 — corrected SQLite locking).

POSTGRESQL (production):
    SELECT pg_advisory_xact_lock(:lock_key)

    - key = deterministic SHA-256 of b"secret:case-flush:" + normalized case id,
      truncated to 8 bytes -> unsigned 64-bit -> signed 64-bit BIGINT.
    - transaction-scoped: PostgreSQL releases the lock automatically when the
      enclosing transaction COMMITs or ROLLBACKs.
    - case-scoped: different cases use different keys; no global lock.

SQLITE (tests / non-PG dev):
    Advisory locks do not exist, so we serialize the same critical section
    using SQLite's transaction file lock:

        UPSERT into integrity_flush_locks  -- an ALWAYS-WRITE statement
        (INSERT ... ON CONFLICT (case_id) DO UPDATE SET holder=:new_holder)

    Why this is correct (and why the previous INSERT ... DO NOTHING was not):
    - A plain INSERT that resolves to "DO NOTHING" because the row already
      exists performs NO write, so it never acquires SQLite's reserved write
      lock — later flushes ran unserialized.
    - An UPSERT that ALWAYS performs a write (holder is a fresh nonce every
      call) acquires the reserved write lock on the FIRST statement of the
      flush transaction, BEFORE any pending rows or the latest block are read.
    - The reserved write lock is held until the enclosing transaction COMMITs
      or ROLLBACKs, then released automatically.
    - No lock rows are "left behind" in a way that matters: the row is a
      token; serialization comes from the transaction's write lock, not from
      the row's existence. Every flush re-writes it inside a fresh transaction.
    - Works across independent AsyncSession instances/connections on the same
      SQLite file (each holds its own connection; the DB engine arbitrates).

    SQLite handles a second concurrent writer by waiting up to the connection's
    busy timeout and then failing with SQLITE_BUSY. Tests set a generous
    `connect_args={"timeout": ...}` so the waiting worker proceeds after the
    first worker commits.

WHY NO PROCESS-LOCAL LOCK
    asyncio.Lock / threading.Lock / module dictionaries / singleton mutexes
    only serialize within one Python process. Two uvicorn workers (or two
    processes) would bypass them entirely, so they are never used here. The
    production guarantee must come from the database.

TRANSACTION BOUNDARY
    `flush_pending()` runs the entire critical section
    (lock -> read pending -> read latest block -> compute -> append block ->
    create LedgerEvents -> mark outbox CONFIRMED) inside the caller's open
    transaction, and RETURNS WITHOUT COMMITTING. The caller commits after
    flush_pending() returns (existing endpoint/service contract). Both the
    lock (PostgreSQL advisory / SQLite write lock) and all writes therefore
    commit or roll back TOGETHER.
"""
from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_LOCK_NAMESPACE = b"secret:case-flush:"


def case_lock_key(case_id) -> int:
    """Deterministic signed 64-bit advisory-lock key from a case identifier.

    Same normalized input -> same key; safe across processes/restarts; never
    Python's randomized hash().
    """
    if isinstance(case_id, (int, float)):
        case_id = str(int(case_id))
    digest = hashlib.sha256(_LOCK_NAMESPACE + str(case_id).encode("utf-8")).digest()[:8]
    value = int.from_bytes(digest, "big")
    # Map unsigned 64-bit into the signed BIGINT range PostgreSQL accepts.
    return value - (1 << 64) if value >= (1 << 63) else value


@asynccontextmanager
async def acquire_case_flush_lock(session: AsyncSession, case_id) -> AsyncIterator[None]:
    """Serialize flush_pending(case_id) across workers/processes.

    The lock is held by the OPEN transaction and released only when that
    transaction commits or rolls back (callers commit after the critical
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
        # SQLite (and other non-PG dialects): an ALWAYS-WRITE UPSERT acquires
        # the engine's reserved write lock for the transaction. The nonce makes
        # the write observable every time so the conflict-update path always
        # executes — never a no-op like INSERT ... ON CONFLICT DO NOTHING.
        normalized = str(int(case_id)) if isinstance(case_id, (int, float)) else str(case_id)
        holder = uuid.uuid4().hex[:8]
        await session.execute(
            text(
                "INSERT INTO integrity_flush_locks (case_id, holder) "
                "VALUES (:case_id, :holder) "
                "ON CONFLICT (case_id) DO UPDATE SET holder = :holder"
            ),
            {"case_id": normalized, "holder": holder},
        )
    try:
        yield
    except Exception:
        # Transaction (and therefore the lock) rolls back with the failure.
        raise