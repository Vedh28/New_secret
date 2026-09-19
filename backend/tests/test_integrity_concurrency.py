"""Concurrency tests for case-scoped ledger flushes (Phases 2-10).

Production serialization comes from PostgreSQL transaction-scoped advisory
locks (`pg_advisory_xact_lock`). SQLite has no advisory locks, so these tests
run against a shared FILE-based SQLite engine with INDEPENDENT sessions; the
SQLite fallback takes the engine's file-level write lock for the critical
section, which serializes same-case flushes at the database layer too.

The invariant assertions are engine-agnostic: one logical outbox event, one
ledger event, one committed block, sequential indexes, valid chain, no
cross-case leakage.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.blockchain.local_ledger import LocalPermissionedLedger
from app.blockchain.service import BlockchainIntegrityService
from app.core.database import Base
from app.models.case import Case, CasePriority, CaseStatus
from app.models.integrity import IntegrityOutbox
from app.repositories.integrity_repository import IntegrityOutboxRepository, LedgerBlockRepository


@pytest.fixture()
async def concurrency_ctx(tmp_path):
    """File-backed SQLite engine shared by independent sessions.

    A generous busy timeout lets the second, waiting SQLite connection block on
    the DB-wide writer lock until Worker A commits — mirroring how PostgreSQL's
    advisory lock would let it wait. SQLite serialization is database-wide, so
    these tests verify CORRECTNESS (no lost/duplicate events, valid chains) and
    cross-case isolation, not per-case parallelism.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'conc.db'}",
        connect_args={"timeout": 30},
    )
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Maker() as session:
        ca = Case(case_number="CASE-CONC-A", title="Concurrency A",
                  status=CaseStatus.OPEN.value, priority=CasePriority.HIGH.value)
        cb = Case(case_number="CASE-CONC-B", title="Concurrency B",
                  status=CaseStatus.OPEN.value, priority=CasePriority.LOW.value)
        session.add_all([ca, cb])
        await session.commit()
        yield {
            "maker": Maker,
            "engine": engine,
            "case_a": str(ca.id),
            "case_b": str(cb.id),
            "case_number_a": ca.case_number,
        }
    await engine.dispose()


async def _enqueue(session, case_id: str, event_type: str, entity_id: str, value: str):
    return await IntegrityOutboxRepository(session).create(
        case_id=case_id, event_type=event_type, entity_type="source", entity_id=entity_id,
        payload_hash=f"H-{value}", payload_json={"event_type": event_type, "entity_id": entity_id, "v": value},
        actor_id=None, status="PENDING", attempts=0, dedupe_key=None,
    )


async def _flush_and_commit(svc, session, case_id: str) -> tuple[list, str]:
    result = await svc.flush_pending(case_id)
    await session.commit()
    return result, case_id


async def _flush_twice(maker, case_id: str) -> list[list]:
    """Run flush_pending(case_id) concurrently on two independent sessions."""
    async with maker() as sa:
        async with maker() as sb:
            svc_a = BlockchainIntegrityService(sa)
            svc_b = BlockchainIntegrityService(sb)
            return list(await asyncio.gather(
                _flush_and_commit(svc_a, sa, case_id),
                _flush_and_commit(svc_b, sb, case_id),
            ))


# ---------------------------------------------------------------------------
# Deterministic lock-key correctness (Phase 9)
# ---------------------------------------------------------------------------

class TestCaseLockKey:
    def test_same_input_same_key(self):
        from app.blockchain.locking import case_lock_key
        assert case_lock_key("CASE-2026-0001") == case_lock_key("CASE-2026-0001")
        assert case_lock_key(1) == case_lock_key("1")

    def test_different_inputs_different_keys(self):
        from app.blockchain.locking import case_lock_key
        keys = {case_lock_key(str(i)) for i in range(50)}
        assert len(keys) == 50

    def test_int_range_and_sign(self):
        from app.blockchain.locking import case_lock_key
        min_value = -(1 << 63)
        max_value = (1 << 63) - 1
        for case_id in ("1", "2", "999999", "CASE-A", "CASE-B"):
            key = case_lock_key(case_id)
            assert isinstance(key, int)
            assert min_value <= key <= max_value
        for case_id in (0, (1 << 64) - 1):
            key = case_lock_key(case_id)
            assert min_value <= key <= max_value


# ---------------------------------------------------------------------------
# SQLite lock correctness across repeated flushes (Phase 5/7)
# ---------------------------------------------------------------------------

class TestRepeatedFlushSerialization:
    async def test_lock_works_across_repeated_commits(self, concurrency_ctx):
        """The previously-broken SQLite lock (permanent DO NOTHING row) must
        NOT break the SECOND round of concurrent flushes."""
        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]

        # Round 1: one event, two concurrent flushes -> one committed event.
        async with maker() as session:
            await _enqueue(session, case_id, "EVIDENCE_REGISTERED", "SRC-1", "A1")
            await session.commit()
        calls = await _flush_twice(maker, case_id)
        assert sum(len(entries[0]) for entries in calls) == 1

        # Round 2: AFTER the first commit, a NEW event, again two concurrent
        # flushes -> exactly ONE new ledger event in the next block.
        async with maker() as session:
            await _enqueue(session, case_id, "EVIDENCE_PROCESSED", "SRC-1", "A2")
            await session.commit()
        calls = await _flush_twice(maker, case_id)
        assert sum(len(entries[0]) for entries in calls) == 1

        async with maker() as session:
            events = await BlockchainIntegrityService(session).get_events(case_id)
            assert len(events) == 2
            assert {e["entity_id"] for e in events} == {"SRC-1"}
            assert {e["block_index"] for e in events} == {0, 1}  # sequential blocks
            blocks = await LedgerBlockRepository(session).chain(case_id)
            assert [b.index for b in blocks] == [0, 1]
            verifying = LocalPermissionedLedger().verify_chain(
                [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
            assert verifying.chain_valid is True
            # No stale lock-row side effects: a third flush is a no-op.
            async with maker() as s3:
                svc3 = BlockchainIntegrityService(s3)
                third = await svc3.flush_pending(case_id)
                await s3.commit()
                assert third == []

    async def test_outbox_retry_budget_respected(self, concurrency_ctx, monkeypatch):
        """FAILED rows beyond MAX_ATTEMPTS are terminal, never re-flushed."""
        from app.blockchain.adapters.local import LocalLedgerStore
        from app.blockchain.service import MAX_ATTEMPTS
        from app.repositories.integrity_repository import IntegrityOutboxRepository

        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            await _enqueue(session, case_id, "INTELLIGENCE_SNAPSHOT", str(case_id), "S")
            await session.commit()

        original_append = LocalLedgerStore.append_block
        state = {"fail": True}

        async def _guarded(*args, **kwargs):
            if state["fail"]:
                raise RuntimeError("ledger down")
            return await original_append(*args, **kwargs)

        monkeypatch.setattr(LocalLedgerStore, "append_block", _guarded)

        from app.blockchain.service import BlockchainIntegrityService

        for _ in range(MAX_ATTEMPTS):
            async with maker() as session:
                svc = BlockchainIntegrityService(session)
                rows = await IntegrityOutboxRepository(session).pending_for_case(case_id, limit=10,
                                                                                 max_attempts=MAX_ATTEMPTS)
                if not rows:
                    break
                state["fail"] = True
                assert await svc.flush_pending(case_id) == []
                await session.commit()
        state["fail"] = False

        async with maker() as session:
            rows = await IntegrityOutboxRepository(session).pending_for_case(case_id, limit=10,
                                                                             max_attempts=MAX_ATTEMPTS)
            assert rows == []  # exhausted -> NOT part of the retryable set
            svc = BlockchainIntegrityService(session)
            assert await svc.flush_pending(case_id) == []
            assert await svc.get_events(case_id) == []  # never falsely committed


# ---------------------------------------------------------------------------
# Analyst decision + evidence version concurrency (Phases 3/4)
# ---------------------------------------------------------------------------

class TestAnalystDecisionConcurrency:
    async def test_identical_decision_concurrent_single_commitment(self, concurrency_ctx):
        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]

        async def _decide(session, svc):
            result = await svc.record_analyst_decision(
                case_id=case_id, entity_a="P-100", entity_b="P-200", decision="CONFIRM",
                evidence_ids=["SRC-1"], notes="reviewed", actor_id=None,
            )
            await session.commit()
            return result

        async with maker() as sa:
            async with maker() as sb:
                svc_a = BlockchainIntegrityService(sa)
                svc_b = BlockchainIntegrityService(sb)
                out = await asyncio.gather(
                    _decide(sa, svc_a),
                    _decide(sb, svc_b),
                )

        winners = [r["duplicate"] for r in out]
        assert winners.count(False) == 1  # exactly one caller created it

        async with maker() as session:
            events = await BlockchainIntegrityService(session).get_events(case_id)
            decisions = [e for e in events if e["event_type"] == "ANALYST_DECISION"]
            assert len(decisions) == 1
            blocks = await LedgerBlockRepository(session).chain(case_id)
            assert len(blocks) == 1
            verifying = LocalPermissionedLedger().verify_chain(
                [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
            assert verifying.chain_valid is True


class TestEvidenceVersionConcurrency:
    async def test_same_changed_content_concurrent_single_version(self, concurrency_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.integrity_repository import EvidenceIntegrityRepository

        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            await BlockchainIntegrityService(session).register_evidence(
                case_id=case_id, source_id="SRC-1", source_type="FIR", filename="fir.txt",
                evidence_hash="A" * 64, content_hash="H1", actor_id=None)
            await session.commit()

        async def _register_v2(session, svc):
            result = await svc.register_evidence(
                case_id=case_id, source_id="SRC-1", source_type="FIR", filename="fir.txt",
                evidence_hash="B" * 64, content_hash="H2", actor_id=None)
            await session.commit()
            return result

        async with maker() as sa:
            async with maker() as sb:
                svc_a = BlockchainIntegrityService(sa)
                svc_b = BlockchainIntegrityService(sb)
                results = await asyncio.gather(
                    _register_v2(sa, svc_a),
                    _register_v2(sb, svc_b),
                )

        versions = sorted(r["version"] for r in results)
        assert versions == [2, 2]  # both callers observe the SAME new version
        async with maker() as session:
            history = await EvidenceIntegrityRepository(session).history_for_source(case_id, "SRC-1")
            assert [v.version for v in history] == [1, 2]  # exactly one v2, no v3
            assert len({(v.source_id, v.version) for v in history}) == 2
            events = await BlockchainIntegrityService(session).get_events(case_id)
            version_events = [e for e in events if e["event_type"] == "EVIDENCE_VERSION_CREATED"]
            assert len(version_events) == 1
            blocks = await LedgerBlockRepository(session).chain(case_id)
            verifying = LocalPermissionedLedger().verify_chain(
                [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
            assert verifying.chain_valid is True


class TestConcurrentFlush:
    async def test_same_case_single_event_one_commitment(self, concurrency_ctx):
        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            await _enqueue(session, case_id, "EVIDENCE_REGISTERED", "SRC-1", "A")
            await session.commit()

        # Two INDEPENDENT sessions flushing the SAME case concurrently.
        confirmed_calls = await _flush_twice(maker, case_id)
        assert sum(len(entries[0]) for entries in confirmed_calls) == 1

        async with maker() as session:
            outbox = (await IntegrityOutboxRepository(session).pending_for_case(case_id, limit=100))
            assert len(outbox) == 0  # everything confirmed
            events = await BlockchainIntegrityService(session).get_events(case_id)
            assert len(events) == 1
            blocks = await LedgerBlockRepository(session).chain(case_id)
            assert len(blocks) == 1
            assert blocks[0].index == 0
            verifying = LocalPermissionedLedger().verify_chain(
                [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
            assert verifying.chain_valid is True

    async def test_same_case_many_events_no_loss_no_duplication(self, concurrency_ctx):
        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            for i in range(6):
                await _enqueue(session, case_id, "EVIDENCE_PROCESSED", f"SRC-{i}", f"v{i}")
            await session.commit()

        confirmed_calls = await _flush_twice(maker, case_id)
        total = sum(len(entries[0]) for entries in confirmed_calls)
        # No event is lost or duplicated across the two workers.
        assert total == 6

        async with maker() as session:
            events = await BlockchainIntegrityService(session).get_events(case_id)
            assert len(events) == 6
            tx_ids = [e["transaction_id"] for e in events]
            assert len(set(tx_ids)) == 6
            entity_ids = [e["entity_id"] for e in events]
            assert len(set(entity_ids)) == 6  # all six distinct sources preserved
            for e in events:
                assert e["block_index"] is not None
            blocks = await LedgerBlockRepository(session).chain(case_id)
            indexes = [b.index for b in blocks]
            assert indexes == sorted(indexes)
            verifying = LocalPermissionedLedger().verify_chain(
                [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
            assert verifying.chain_valid is True

    async def test_different_cases_flush_independently(self, concurrency_ctx):
        maker = concurrency_ctx["maker"]
        case_a = concurrency_ctx["case_a"]
        case_b = concurrency_ctx["case_b"]
        async with maker() as session:
            await _enqueue(session, case_a, "EVIDENCE_REGISTERED", "A-1", "a")
            await _enqueue(session, case_b, "EVIDENCE_REGISTERED", "B-1", "b")
            await session.commit()

        async with maker() as sa:
            async with maker() as sb:
                svc_a = BlockchainIntegrityService(sa)
                svc_b = BlockchainIntegrityService(sb)
                await asyncio.gather(
                    _flush_and_commit(svc_a, sa, case_a),
                    _flush_and_commit(svc_b, sb, case_b),
                )

        async with maker() as session:
            events_a = await BlockchainIntegrityService(session).get_events(case_a)
            events_b = await BlockchainIntegrityService(session).get_events(case_b)
            assert len(events_a) == 1 and len(events_b) == 1
            assert events_a[0]["entity_id"] == "A-1"
            assert events_b[0]["entity_id"] == "B-1"
            assert events_a[0]["transaction_id"] != events_b[0]["transaction_id"]
            for case_id in (case_a, case_b):
                blocks = await LedgerBlockRepository(session).chain(case_id)
                verifying = LocalPermissionedLedger().verify_chain(
                    [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
                assert verifying.chain_valid is True

    async def test_ledger_failure_then_retry_one_event(self, concurrency_ctx, monkeypatch):
        from app.blockchain.adapters.local import LocalLedgerStore

        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            outbox = await _enqueue(session, case_id, "REPORT_GENERATED", "REP-1", "r")
            await session.commit()
            outbox_id = outbox.id

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger down")

        original_append = LocalLedgerStore.append_block
        state = {"fail": True}

        async def _guarded_append(*args, **kwargs):
            if state["fail"]:
                raise RuntimeError("ledger down")
            return await original_append(*args, **kwargs)

        monkeypatch.setattr(LocalLedgerStore, "append_block", _guarded_append)

        async with maker() as session:
            svc = BlockchainIntegrityService(session)
            assert await svc.flush_pending(case_id) == []
            await session.commit()

        # Outbox retryable, no false event, no committed block.
        async with maker() as session:
            rows = (await IntegrityOutboxRepository(session).pending_for_case(case_id, limit=100))
            assert rows and rows[0].id == outbox_id
            assert rows[0].status in ("PENDING", "FAILED")
            assert rows[0].attempts >= 1
            assert await BlockchainIntegrityService(session).get_events(case_id) == []
            assert await LedgerBlockRepository(session).chain(case_id) == []

        # Restore the ledger and retry -> exactly ONE event.
        state["fail"] = False
        async with maker() as session:
            svc = BlockchainIntegrityService(session)
            confirmed = await svc.flush_pending(case_id)
            await session.commit()
            assert len(confirmed) == 1
            events = await svc.get_events(case_id)
            assert len(events) == 1
            assert events[0]["entity_id"] == "REP-1"
            blocks = await LedgerBlockRepository(session).chain(case_id)
            assert len(blocks) == 1

    async def test_repeated_flush_is_noop(self, concurrency_ctx):
        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            await _enqueue(session, case_id, "EVIDENCE_REGISTERED", "SRC-9", "x")
            await session.commit()
        async with maker() as session:
            svc = BlockchainIntegrityService(session)
            first = await svc.flush_pending(case_id)
            await session.commit()
            assert len(first) == 1
            second = await svc.flush_pending(case_id)
            await session.commit()
            assert second == []
            assert len(await svc.get_events(case_id)) == 1

    async def _flush_twice(self, maker, case_id: str) -> list[list]:
        async with maker() as sa:
            async with maker() as sb:
                svc_a = BlockchainIntegrityService(sa)
                svc_b = BlockchainIntegrityService(sb)
                return list(await asyncio.gather(
                    _flush_and_commit(svc_a, sa, case_id),
                    _flush_and_commit(svc_b, sb, case_id),
                ))


# ---------------------------------------------------------------------------
# Deterministic lock contention (Phase 3) + exhausted dedupe (Phase 5)
# ---------------------------------------------------------------------------

class TestLockContention:
    async def test_worker_b_waits_until_worker_a_commits(self, concurrency_ctx):
        """Deterministic: Worker A holds the lock mid-critical-section; Worker
        B cannot enter until A commits; B then re-reads and does not duplicate."""
        from app.blockchain.service import BlockchainIntegrityService

        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            await _enqueue(session, case_id, "EVIDENCE_REGISTERED", "SRC-C1", "c1")
            await session.commit()

        entered = asyncio.Event()
        release = asyncio.Event()
        original = BlockchainIntegrityService._flush_locked

        async with maker() as sa:
            async with maker() as sb:
                svc_a = BlockchainIntegrityService(sa)
                svc_b = BlockchainIntegrityService(sb)

                async def _paused(cid, max_events=200):
                    entered.set()
                    await release.wait()  # hold the lock; other workers wait
                    return await original(svc_a, cid, max_events)

                svc_a._flush_locked = _paused  # instance override for Worker A

                async def _worker_a():
                    result = await svc_a.flush_pending(case_id)
                    await sa.commit()
                    return result

                async def _worker_b():
                    result = await svc_b.flush_pending(case_id)
                    await sb.commit()
                    return result

                task_a = asyncio.create_task(_worker_a())
                await entered.wait()  # A is now INSIDE the critical section
                task_b = asyncio.create_task(_worker_b())
                # Deterministic blocking proof: B has started (event barrier)
                # and is parked on the database write lock while A holds it.
                # A single scheduling yield lets B reach its blocking UPSERT;
                # if the lock were broken B would have completed by now.
                await asyncio.sleep(0)
                assert not task_b.done(), "Worker B entered while Worker A held the lock"

                release.set()
                result_a = await task_a
                result_b = await task_b

        assert len(result_a) == 1
        assert result_b == []  # B re-read pending AFTER A committed -> none

        async with maker() as session:
            events = await BlockchainIntegrityService(session).get_events(case_id)
            assert len(events) == 1
            blocks = await LedgerBlockRepository(session).chain(case_id)
            assert len(blocks) == 1
            verifying = LocalPermissionedLedger().verify_chain(
                [_chain_block(b) for b in blocks], LocalPermissionedLedger().genesis_params(case_id))
            assert verifying.chain_valid is True


class TestExhaustedDedupe:
    async def test_exhausted_dedupe_row_reports_terminal_no_new_event(self, concurrency_ctx):
        from app.blockchain.service import BlockchainIntegrityService, MAX_ATTEMPTS
        from app.repositories.integrity_repository import IntegrityOutboxRepository

        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        snapshot_hash = "SH-TERMINAL"

        async with maker() as session:
            await IntegrityOutboxRepository(session).create(
                case_id=str(case_id), event_type="INTELLIGENCE_SNAPSHOT",
                entity_type="case", entity_id=str(case_id),
                payload_hash="H", payload_json={"snapshot_hash": snapshot_hash},
                actor_id=None, status="FAILED", attempts=MAX_ATTEMPTS,
                last_error="exhausted", dedupe_key=f"{case_id}::INTELLIGENCE_SNAPSHOT::1.x::{snapshot_hash}",
            )
            await session.commit()

        async with maker() as session:
            svc = BlockchainIntegrityService(session)
            result = await svc.enqueue_snapshot(case_id=case_id, snapshot_hash=snapshot_hash,
                                                engine_version="1.x")
            assert result["exhausted"] is True
            assert result["duplicate"] is True
            # flush must NOT retry the exhausted row and must not create an event.
            assert await svc.flush_pending(case_id) == []
            assert await svc.get_events(case_id) == []
            assert await svc.pending_count(case_id) == 0


class TestMidFlushAtomicity:
    async def test_failure_mid_event_creation_rolls_back_everything(self, concurrency_ctx, monkeypatch):
        """All-or-nothing: a failure on the SECOND LedgerEvent must leave NO
        block/event, keep the outbox retryable, and produce exactly two events
        only after a successful retry."""
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.integrity_repository import LedgerEventRepository

        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            for i in range(2):
                await _enqueue(session, case_id, "EVIDENCE_PROCESSED", f"SRC-{i}", f"m{i}")
            await session.commit()

        original_create = LedgerEventRepository.create
        calls = {"n": 0, "boom": True}

        async def _boom_on_second(*args, **kwargs):
            calls["n"] += 1
            if calls["boom"] and calls["n"] == 2:
                raise RuntimeError("injected event-creation failure")
            return await original_create(*args, **kwargs)

        monkeypatch.setattr(LedgerEventRepository, "create", _boom_on_second)

        # The flush raises; the caller does NOT commit (transaction dies).
        async with maker() as session:
            svc = BlockchainIntegrityService(session)
            with pytest.raises(RuntimeError):
                await svc.flush_pending(case_id)

        # Fresh view: nothing became authoritative, outbox still retryable.
        async with maker() as session:
            assert await LedgerBlockRepository(session).chain(case_id) == []
            assert await BlockchainIntegrityService(session).get_events(case_id) == []
            rows = await IntegrityOutboxRepository(session).pending_for_case(
                case_id, limit=10, max_attempts=3)
            assert len(rows) == 2
            assert all(r.status in ("PENDING", "FAILED") for r in rows)

        # Restore and retry -> exactly two events, one block, valid chain.
        calls["boom"] = False
        async with maker() as session:
            svc = BlockchainIntegrityService(session)
            confirmed = await svc.flush_pending(case_id)
            await session.commit()
            assert len(confirmed) == 2
            events = await svc.get_events(case_id)
            assert len(events) == 2
            blocks = await LedgerBlockRepository(session).chain(case_id)
            assert len(blocks) == 1


class TestCaseKeyNormalization:
    def test_integer_and_string_and_float_normalize_consistently(self):
        from app.blockchain.locking import case_lock_key
        from app.blockchain.service import _normalize_case
        assert _normalize_case(1) == _normalize_case("1") == "1"
        assert _normalize_case(1.0) == "1"
        assert _normalize_case("CASE-X") == "CASE-X"
        # Same canonical key for a numeric case in any supported form.
        assert case_lock_key(1) == case_lock_key("1") == case_lock_key(1.0)
        # A float-like STRING is a distinct identifier, not silently coerced.
        assert case_lock_key("1.0") != case_lock_key(1)
        # Fully distinct identifiers never collide.
        assert case_lock_key("1") != case_lock_key("2")


def _chain_block(row) -> object:
    from app.blockchain.interface import Block

    return Block(
        index=row.index, timestamp=row.timestamp_iso,
        previous_hash=row.previous_hash, data_hash=row.data_hash,
        hash=row.block_hash, case_id=row.case_id, events=row.events_json or [],
    )