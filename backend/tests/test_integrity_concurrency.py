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
    """File-backed SQLite engine shared by independent sessions."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'conc.db'}")
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


class TestConcurrentFlush:
    async def test_same_case_single_event_one_commitment(self, concurrency_ctx):
        maker = concurrency_ctx["maker"]
        case_id = concurrency_ctx["case_a"]
        async with maker() as session:
            await _enqueue(session, case_id, "EVIDENCE_REGISTERED", "SRC-1", "A")
            await session.commit()

        # Two INDEPENDENT sessions flushing the SAME case concurrently.
        confirmed_calls = await self._flush_twice(maker, case_id)
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

        confirmed_calls = await self._flush_twice(maker, case_id)
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


def _chain_block(row) -> object:
    from app.blockchain.interface import Block

    return Block(
        index=row.index, timestamp=row.timestamp_iso,
        previous_hash=row.previous_hash, data_hash=row.data_hash,
        hash=row.block_hash, case_id=row.case_id, events=row.events_json or [],
    )