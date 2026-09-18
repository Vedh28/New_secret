"""BlockchainEvidenceIntegrityService blocks/integrity service (Phases 4-15).

Orchestrates the OUTBOX pattern and the local permissioned ledger:

    business write (evidence/decision/report/snapshot)
        -> integrity outbox row (PENDING)
        -> flush_pending builds ONE chained block for the case
        -> ledger_events row per event (transaction id, block, hashes)
        -> outbox CONFIRMED

Only on-chain event references + hashes are stored on the chain; sensitive
content NEVER leaves the authoritative (PostgreSQL) case store. If appending to
the ledger fails, outbox rows become FAILED and the integrity layer reports
UNAVAILABLE / PENDING — the investigation pipeline continues unaffected.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain import hashes, merkle
from app.blockchain.adapters.local import LocalLedgerStore, get_ledger_engine
from app.blockchain.hashes import (
    canonical_evidence_payload,
    hash_decision_payload,
    hash_evidence_payload,
    hash_intelligence_snapshot,
    hash_json,
    hash_report_payload,
    hash_text,
)
from app.blockchain.local_ledger import LocalPermissionedLedger
from app.models.integrity import CHAIN_STATUS, INTEGRITY_STATUS, OUTBOX_STATUS
from app.repositories.integrity_repository import (
    EvidenceIntegrityRepository,
    IntegrityOutboxRepository,
    LedgerEventRepository,
)
from app.repositories.source_repository import SourceRepository

logger = logging.getLogger("secret.integrity")

MAX_ATTEMPTS = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tx_id() -> str:
    return f"TX-{uuid.uuid4().hex[:16].upper()}"


def _normalize_case(case_id) -> str:
    """Ledger tables key on the numeric case id as its canonical string."""
    return str(int(case_id)) if isinstance(case_id, (int, float)) else str(case_id)


class BlockchainIntegrityService:
    """Case-scoped evidence / integrity orchestration layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._engine = get_ledger_engine()
        self._store = LocalLedgerStore(session, self._engine if isinstance(self._engine, LocalPermissionedLedger) else None)

    # ------------------------------------------------------------------
    # OUTBOX + chamber append
    # ------------------------------------------------------------------
    async def enqueue(self, *, case_id: str, event_type: str, entity_type: str | None,
                      entity_id: str | None, payload: dict, actor_id: int | None) -> Any:
        case_id = _normalize_case(case_id)
        payload_hash = hash_json(payload)
        return await IntegrityOutboxRepository(self._session).create(
            case_id=case_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload_hash=payload_hash,
            payload_json=payload,
            actor_id=actor_id,
            status="PENDING",
            attempts=0,
        )

    async def flush_pending(self, case_id: str, max_events: int = 200) -> list[dict]:
        """Append ONE chained block for the case containing pending events.

        The per-case lock (advisory on PostgreSQL; DB-wide write lock on SQLite)
        is acquired BEFORE pending rows are read and held until the caller
        commits/rolls back. The locked critical section is extracted into
        ``_flush_locked`` so integration tests can pause Worker A inside it
        and prove Worker B truly blocks.
        """
        case_id = _normalize_case(case_id)
        from app.blockchain.locking import acquire_case_flush_lock

        async with acquire_case_flush_lock(self._session, case_id):
            return (await self._flush_locked(case_id, max_events)) or []

    # Extracted so tests can monkeypatch it and insert a deterministic pause
    # while the lock is held.
    async def _flush_locked(self, case_id: str, max_events: int = 200) -> list[dict] | None:
        """The actual read → compute → append → confirm critical section.

        Must be called WHILE the case lock is already held.  Returns [] when
        there is nothing pending, or a list of confirmed outbox entries.
        """
        pending = await IntegrityOutboxRepository(self._session).pending_for_case(
            case_id, limit=max_events, max_attempts=MAX_ATTEMPTS)
        if not pending:
            return None

        latest = await self._store.latest_block(case_id)
        events: list[dict] = []
        planned: list[tuple] = []
        for outbox in pending:
            tx = _tx_id()
            ev = {
                "transaction_id": tx,
                "event_type": outbox.event_type,
                "entity_type": outbox.entity_type,
                "entity_id": outbox.entity_id,
                "payload_hash": outbox.payload_hash,
                "payload_json": outbox.payload_json,
                "actor_id": outbox.actor_id,
                "hash": outbox.payload_hash,
            }
            events.append(ev)
            planned.append((outbox, tx))

        try:
            block = self._engine.compute_block(previous=latest, case_id=case_id, events=events)
            await self._store.append_block(block)
        except Exception as exc:  # noqa: BLE001 - integrity outage must not break case work
            logger.warning("integrity ledger append failed for case=%s events=%d: %s",
                           case_id, len(planned), exc)
            for outbox, _tx in planned:
                outbox.attempts = (outbox.attempts or 0) + 1
                outbox.last_error = str(exc)[:500]
                outbox.status = "FAILED" if outbox.attempts >= MAX_ATTEMPTS else "PENDING"
                await IntegrityOutboxRepository(self._session).save(outbox)
            return []

        event_repo = LedgerEventRepository(self._session)
        outbox_repo = IntegrityOutboxRepository(self._session)
        confirmed: list[dict] = []
        for outbox, tx in planned:
            await event_repo.create(
                transaction_id=tx,
                case_id=case_id,
                event_type=outbox.event_type,
                entity_type=outbox.entity_type,
                entity_id=outbox.entity_id,
                payload_hash=outbox.payload_hash,
                payload_json=outbox.payload_json,
                actor_id=outbox.actor_id,
                block_index=block.index,
                block_hash=block.hash,
                previous_block_hash=block.previous_hash,
                status="REGISTERED",
            )
            outbox.status = "CONFIRMED"
            outbox.ledger_transaction_id = tx
            outbox.processed_at = datetime.now(timezone.utc)
            outbox.last_error = None  # cleared on a successful retry
            await outbox_repo.save(outbox)
            confirmed.append({"outbox_id": outbox.id, "transaction_id": tx, "block_index": block.index})
        return confirmed

    async def _append_and_link(self, *, case_id: str, event_type: str, entity_type: str | None,
                               entity_id: str | None, payload: dict, actor_id: int | None,
                               link_transaction_id: str | None = None) -> dict:
        """Enqueue an event and flush it; returns the flush outcome."""
        case_id = _normalize_case(case_id)
        await self.enqueue(case_id=case_id, event_type=event_type, entity_type=entity_type,
                           entity_id=entity_id, payload=payload, actor_id=actor_id)
        confirmed = await self.flush_pending(case_id)
        for entry in confirmed:
            return entry
        return {"outbox_id": None, "transaction_id": None, "block_index": None, "scheduled": True}

    # ------------------------------------------------------------------
    # Evidence registration + versioning (Phases 4/6)
    # ------------------------------------------------------------------
    async def register_evidence(self, *, case_id: str, source_id: str, source_type: str,
                                filename: str, evidence_hash: str, content_hash: str,
                                actor_id: int | None) -> dict:
        """Register a source's integrity fingerprint (first/next version).

        An identical content hash does NOT create a new version. A changed
        content hash creates the next version and records an
        EVIDENCE_VERSION_CREATED event.
        """
        case_id = _normalize_case(case_id)
        repo = EvidenceIntegrityRepository(self._session)
        from app.blockchain.locking import acquire_case_flush_lock

        async with acquire_case_flush_lock(self._session, case_id):
            # Serialized per case: version allocation + insert cannot race with
            # a same-case concurrent registration, so the unique constraint is
            # the backstop rather than a normal exception path.
            latest = await repo.latest_for_source(case_id, source_id)
            if latest is not None and latest.content_hash == content_hash:
                return self._evidence_read(latest)

            version = (latest.version + 1) if latest is not None else 1
            event_type = "EVIDENCE_VERSION_CREATED" if latest is not None else "EVIDENCE_REGISTERED"
            payload = {
                "event_type": event_type,
                "case_id": str(case_id),
                "source_id": str(source_id),
                "evidence_hash": str(evidence_hash),
                "content_hash": str(content_hash),
                "hash_algorithm": "SHA-256",
                "source_type": str(source_type or ""),
                "filename_hash": hash_text(filename),
                "version": version,
                "actor_id": str(actor_id or ""),
            }

            row = await repo.create(
                case_id=case_id, source_id=source_id, evidence_hash=evidence_hash,
                content_hash=content_hash, hash_algorithm="SHA-256", version=version,
                status="REGISTERED", actor_id=actor_id,
            )
            outcome = await self._append_and_link(
                case_id=case_id, event_type=payload["event_type"], entity_type="source",
                entity_id=source_id, payload=payload, actor_id=actor_id,
            )
            if outcome.get("transaction_id"):
                row.transaction_id = outcome["transaction_id"]
                row.block_index = outcome["block_index"]
                await repo.save(row)
            return self._evidence_read(row)

    def _evidence_read(self, row, confirm: bool = False) -> dict:
        status = "PENDING" if (row.transaction_id is None and not confirm) else row.status
        return {
            "case_id": row.case_id,
            "source_id": row.source_id,
            "evidence_hash": row.evidence_hash,
            "content_hash": row.content_hash,
            "hash_algorithm": row.hash_algorithm,
            "version": row.version,
            "status": status,
            "transaction_id": row.transaction_id,
            "block_index": row.block_index,
            "actor_id": row.actor_id,
            "created_at": row.created_at.isoformat() if row.created_at else "",
        }

    # ------------------------------------------------------------------
    # Post-processing events + record batch (Phase 9)
    # ------------------------------------------------------------------
    async def register_processed_batch(self, *, case_id: str, source_id: str, source_type: str,
                                       records: list[dict], actor_id: int | None,
                                       extraction: dict | None = None) -> dict:
        """Register the full post-processing integrity surface for a source.

        Enqueues EVIDENCE_PROCESSED, RECORD_BATCH_REGISTERED,
        ENTITY_EXTRACTED and RELATIONSHIP_DERIVED as ONE batch and flushes them
        into a single chained block during the same processing operation.
        """
        case_id = _normalize_case(case_id)
        record_hashes = [hashes.hash_canonical_record(record) for record in records]
        batch = merkle.batch_integrity(record_hashes) if record_hashes else None

        extraction = extraction or {}
        processed = {
            "event_type": "EVIDENCE_PROCESSED",
            "case_id": str(case_id),
            "source_id": str(source_id),
            "source_type": str(source_type or ""),
            "record_count": len(records),
            "merkle_root": batch["merkle_root"] if batch else None,
            "batch_algorithm": "MERKLE-SHA256" if batch else None,
            "entities_extracted": extraction.get("entities", 0),
            "relationships_extracted": extraction.get("relationships", 0),
            "actor_id": str(actor_id or ""),
        }
        await self.enqueue(case_id=case_id, event_type="EVIDENCE_PROCESSED",
                           entity_type="source", entity_id=source_id,
                           payload=processed, actor_id=actor_id)

        if batch:
            await self.enqueue(case_id=case_id, event_type="RECORD_BATCH_REGISTERED",
                               entity_type="source", entity_id=source_id,
                               payload={
                                   "event_type": "RECORD_BATCH_REGISTERED",
                                   "case_id": str(case_id),
                                   "source_id": str(source_id),
                                   "record_count": len(records),
                                   "merkle_root": batch["merkle_root"],
                                   "batch_algorithm": "MERKLE-SHA256",
                                   "actor_id": str(actor_id or ""),
                               }, actor_id=actor_id)

        for event_type, count_field, count in (
            ("ENTITY_EXTRACTED", "entities", extraction.get("entities", 0)),
            ("RELATIONSHIP_DERIVED", "relationships", extraction.get("relationships", 0)),
        ):
            await self.enqueue(case_id=case_id, event_type=event_type,
                               entity_type="source", entity_id=source_id,
                               payload={
                                   "event_type": event_type,
                                   "case_id": str(case_id),
                                   "source_id": str(source_id),
                                   "count": int(count or 0),
                                   "actor_id": str(actor_id or ""),
                               }, actor_id=actor_id)

        # ONE flush -> one chained block carrying all four events.
        confirmed = await self.flush_pending(case_id)
        primary = confirmed[0] if confirmed else {}
        return {
            **processed,
            "merkle_root": batch["merkle_root"] if batch else None,
            "transaction_id": primary.get("transaction_id"),
            "block_index": primary.get("block_index"),
        }

    # ------------------------------------------------------------------
    # Analyst decision integrity (Phase 12)
    # ------------------------------------------------------------------
    async def record_analyst_decision(self, *, case_id: str, entity_a: str, entity_b: str,
                                      decision: str, evidence_ids: list[str], notes: str | None,
                                      actor_id: int | None, snapshot_hash: str = "") -> dict:
        case_id = _normalize_case(case_id)
        pair = f"{entity_a}<->{entity_b}"
        payload = hash_decision_payload(
            case_id=case_id, entity_a=entity_a, entity_b=entity_b, decision=decision,
            evidence_ids_hash=hash_json(sorted(evidence_ids or [])),
            notes_hash=hash_text(notes or ""), analyst_id=actor_id, snapshot_hash=snapshot_hash,
        )
        payload["event_type"] = "ANALYST_DECISION"
        payload_hash = hash_json(payload)
        dedupe_key = f"{case_id}::ANALYST_DECISION::{pair}::{payload_hash}"

        # Atomic, DB-unique identity: identical decisions for the same pair
        # collapse onto ONE logical outbox row / event (no endless duplicates).
        dedupe = await self._dedupe_outbox(
            case_id=case_id, dedupe_key=dedupe_key, event_type="ANALYST_DECISION",
            entity_type="potential_link", entity_id=pair, payload=payload, actor_id=actor_id,
        )
        transaction_id = dedupe.get("transaction_id")
        block_index = None
        if dedupe["state"] in ("created", "retried", "reused_pending"):
            confirmed = await self.flush_pending(case_id)
            transaction_id = confirmed[0]["transaction_id"] if confirmed else transaction_id
            block_index = confirmed[0]["block_index"] if confirmed else None
        return {**payload,
                "duplicate": dedupe["state"] in ("confirmed", "failed_exhausted"),
                "exhausted": dedupe["state"] == "failed_exhausted",
                "transaction_id": transaction_id, "block_index": block_index}

    # ------------------------------------------------------------------
    # Intelligence snapshot integrity (Phase 11 -> Phase 3 idempotent)
    # ------------------------------------------------------------------
    async def _find_event(self, case_id: str, event_type: str, entity_id: str | None,
                          payload_hash: str) -> dict | None:
        """Return an existing confirmed event or pending outbox row matching
        (event_type, entity_id, payload_hash) for a case — nil duplicates."""
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=2000)
        for e in events:
            if e.event_type == event_type and e.entity_id == entity_id and e.payload_hash == payload_hash:
                return {"transaction_id": e.transaction_id, "block_index": e.block_index}
        pending = await IntegrityOutboxRepository(self._session).pending_for_case(
            case_id, limit=500, max_attempts=MAX_ATTEMPTS)
        for outbox in pending:
            if outbox.event_type == event_type and outbox.entity_id == entity_id \
                    and outbox.payload_hash == payload_hash:
                return {"transaction_id": None, "block_index": None, "pending": True}
        return None

    # ------------------------------------------------------------------
    # Atomic snapshot idempotency (Phases 1-3)
    #
    # The canonical identity is  case_id + event_type + engine_version +
    # snapshot_hash, enforced by a DATABASE-LEVEL unique index on
    # integrity_outbox.dedupe_key — not an in-memory lock, so concurrently
    # processed requests collapse onto a single outbox identity.
    # ------------------------------------------------------------------
    @staticmethod
    def _snapshot_dedupe_key(case_id, engine_version, snapshot_hash) -> str:
        return (f"{case_id}::INTELLIGENCE_SNAPSHOT::{engine_version}::{snapshot_hash}")

    async def snapshot_hash_confirmed(self, case_id: str, snapshot_hash: str) -> bool:
        """True when this exact snapshot fingerprint was already committed."""
        case_id = _normalize_case(case_id)
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=2000)
        return any(e.event_type == "INTELLIGENCE_SNAPSHOT"
                   and e.payload_json.get("snapshot_hash") == snapshot_hash for e in events)

    async def _dedupe_outbox(self, *, case_id: str, dedupe_key: str, event_type: str,
                             entity_type: str | None, entity_id: str | None,
                             payload: dict, actor_id: int | None) -> dict:
        """Atomically create/reuse one outbox identity.

        Runs under the per-case flush lock so competing workers serialize their
        check-then-insert (no IntegrityError race in normal operation). The
        unique index on dedupe_key remains as the database-level backstop.

        Returns {"state": created|retried|reused_pending|confirmed|
                 failed_exhausted, "outbox", "transaction_id"}.
        """
        case_id = _normalize_case(case_id)
        repo = IntegrityOutboxRepository(self._session)
        from app.blockchain.locking import acquire_case_flush_lock

        async with acquire_case_flush_lock(self._session, case_id):
            existing = await repo.get_by_dedupe_key(case_id, dedupe_key)
            if existing is not None:
                if existing.status == "CONFIRMED":
                    return {"state": "confirmed", "outbox": existing,
                            "transaction_id": existing.ledger_transaction_id}
                if existing.status == "PENDING":
                    return {"state": "reused_pending", "outbox": existing,
                            "transaction_id": existing.ledger_transaction_id}
                # FAILED -> retry the SAME identity; never a duplicate event.
                # The retry budget caps implicit re-queues; an exhausted row
                # stays terminal (explicit manual intervention can requeue it).
                if (existing.attempts or 0) >= MAX_ATTEMPTS:
                    logger.warning("integrity outbox retry budget exhausted id=%s event=%s case=%s attempts=%s",
                                   existing.id, event_type, case_id, existing.attempts)
                    return {"state": "failed_exhausted", "outbox": existing,
                            "transaction_id": existing.ledger_transaction_id}
                existing.status = "PENDING"
                existing.attempts = (existing.attempts or 0) + 1
                logger.info("integrity outbox retry id=%s event=%s case=%s", existing.id, event_type, case_id)
                await repo.save(existing)
                return {"state": "retried", "outbox": existing,
                        "transaction_id": existing.ledger_transaction_id}

            # Serialized by the case lock: no same-case writer can be inserting
            # the same identity concurrently. A conflict now means a non-locked
            # or cross-case anomaly — surface it rather than guessing.
            outbox = await repo.create(
                case_id=case_id, event_type=event_type, entity_type=entity_type,
                entity_id=entity_id, payload_hash=hash_json(payload),
                payload_json=payload, actor_id=actor_id, status="PENDING",
                attempts=0, dedupe_key=dedupe_key,
            )
            return {"state": "created", "outbox": outbox, "transaction_id": None}

    async def register_intelligence_snapshot(self, *, case_id: str, snapshot: dict,
                                             actor_id: int | None = None) -> dict:
        case_id = _normalize_case(case_id)
        snapshot_hash = hash_intelligence_snapshot(snapshot)
        if await self.snapshot_hash_confirmed(case_id, snapshot_hash):
            return {"duplicate": True, "snapshot_hash": snapshot_hash, "case_id": case_id}
        payload = {
            "event_type": "INTELLIGENCE_SNAPSHOT",
            "case_id": str(case_id),
            "engine": "CaseIntelligenceService",
            "engine_version": "1.x",
            "snapshot_hash": snapshot_hash,
            "created_at": _now_iso(),
            "actor_id": str(actor_id or ""),
        }
        dedupe = await self._dedupe_outbox(
            case_id=case_id, dedupe_key=self._snapshot_dedupe_key(case_id, "1.x", snapshot_hash),
            event_type="INTELLIGENCE_SNAPSHOT", entity_type="case", entity_id=str(case_id),
            payload=payload, actor_id=actor_id,
        )
        transaction_id = dedupe.get("transaction_id")
        block_index = None
        if dedupe["state"] in ("created", "retried", "reused_pending"):
            confirmed = await self.flush_pending(case_id)
            transaction_id = confirmed[0]["transaction_id"] if confirmed else transaction_id
            block_index = confirmed[0]["block_index"] if confirmed else None
        return {
            **payload,
            "duplicate": dedupe["state"] in ("confirmed", "failed_exhausted"),
            "exhausted": dedupe["state"] == "failed_exhausted",
            "transaction_id": transaction_id,
            "block_index": block_index,
        }

    async def enqueue_snapshot(self, *, case_id, snapshot_hash: str, engine_version: str = "1.x",
                               actor_id: int | None = None) -> dict:
        """Idempotent snapshot enqueue (case + snapshot_hash + engine_version).

        Backed by the dedupe_key unique index: concurrent duplicate enqueues
        collapse onto one outbox identity; confirmed snapshots short-circuit.
        """
        case_id = _normalize_case(case_id)
        if await self.snapshot_hash_confirmed(case_id, snapshot_hash):
            return {"duplicate": True, "snapshot_hash": snapshot_hash, "case_id": case_id}
        payload = {
            "event_type": "INTELLIGENCE_SNAPSHOT",
            "case_id": str(case_id),
            "engine": "CaseIntelligenceService",
            "engine_version": engine_version,
            "snapshot_hash": snapshot_hash,
            "created_at": _now_iso(),
            "actor_id": str(actor_id or ""),
        }
        dedupe = await self._dedupe_outbox(
            case_id=case_id, dedupe_key=self._snapshot_dedupe_key(case_id, engine_version, snapshot_hash),
            event_type="INTELLIGENCE_SNAPSHOT", entity_type="case", entity_id=str(case_id),
            payload=payload, actor_id=actor_id,
        )
        return {
            "duplicate": dedupe["state"] in ("confirmed", "reused_pending", "failed_exhausted"),
            "retried": dedupe["state"] == "retried",
            "exhausted": dedupe["state"] == "failed_exhausted",
            "snapshot_hash": snapshot_hash,
            "case_id": case_id,
            "transaction_id": dedupe.get("transaction_id"),
        }

    # ------------------------------------------------------------------
    # Report integrity (Phase 13)
    # ------------------------------------------------------------------
    async def register_report(self, *, case_id: str, report: Any, actor_id: int | None = None,
                              report_hash: str | None = None) -> dict:
        case_id = _normalize_case(case_id)
        if not report_hash:
            report_payload = hashes.report_integrity_payload(
                report_id=report.id, report_type=report.report_type, title=report.title,
                sections=list(report.sections), generated_at=getattr(report, "generated_at", ""),
            )
            report_hash = hash_report_payload(report_payload)
        payload = {
            "event_type": "REPORT_GENERATED",
            "case_id": str(case_id),
            "report_id": report.id,
            "report_type": report.report_type,
            "report_hash": report_hash,
            "generated_at": str(getattr(report, "generated_at", "")),
            "generator": "reports/service.py",
            "actor_id": str(actor_id or ""),
        }
        outcome = await self._append_and_link(
            case_id=case_id, event_type="REPORT_GENERATED",
            entity_type="report", entity_id=report.id, payload=payload, actor_id=actor_id,
        )
        return {**payload, "transaction_id": outcome.get("transaction_id"), "block_index": outcome.get("block_index")}

    # ------------------------------------------------------------------
    # Reads + verification (Phases 10/14/26)
    # ------------------------------------------------------------------
    async def case_summary(self, case_id: str) -> dict:
        case_id = _normalize_case(case_id)
        chain = await self._store.get_chain(case_id)
        chain_valid, chain_status, issues = self._chain_status(case_id, chain)

        events_repo = LedgerEventRepository(self._session)
        ev_repo = EvidenceIntegrityRepository(self._session)
        evidence = await ev_repo.list_by_case(case_id)

        registered = len(evidence)
        matches = await self._verify_stored_evidence(case_id, evidence)
        verified = sum(1 for check in matches if check["status"] == "VERIFIED")
        mismatches = sum(1 for check in matches if check["status"] == "MISMATCH")

        all_events = await events_repo.list_by_case(case_id, limit=5000)
        snapshots = [e for e in all_events if e.event_type == "INTELLIGENCE_SNAPSHOT"]
        report_events = [e for e in all_events if e.event_type == "REPORT_GENERATED"]

        # Registered vs ACTUALLY verified: an event existing does not mean the
        # current persisted object still matches its registered commitment.
        registered_snapshots = len(snapshots)
        registered_reports = len(report_events)
        verified_snapshots = await self._count_verified_snapshots(case_id, snapshots)
        verified_reports = await self._count_verified_reports(case_id, report_events)

        latest_block = chain[-1] if chain else None
        return {
            "case_id": case_id,
            "chain_status": chain_status,
            "chain_valid": chain_valid,
            "blocks": len(chain),
            "events": len(all_events),
            "evidence_registered": registered,
            "evidence_verified": verified,
            "mismatches": mismatches,
            "registered_snapshots": registered_snapshots,
            "verified_snapshots": verified_snapshots,
            "registered_reports": registered_reports,
            "verified_reports": verified_reports,
            "latest_block": _block_read(latest_block),
            "issues": issues[:10],
        }

    async def _count_verified_snapshots(self, case_id: str, snapshots: list) -> int:
        """How many snapshot commitments match the CURRENT intelligence.

        Only fingerprints equal to the current canonical snapshot count as
        verified — event existence alone never does.
        """
        if not snapshots:
            return 0
        try:
            from app.services.case_intelligence_service import CaseIntelligenceService
            snapshot = await CaseIntelligenceService(self._session).build(
                int(case_id), cache={}, register_integrity=False,
            )
            from app.blockchain.hashes import hash_intelligence_snapshot
            current = hash_intelligence_snapshot(snapshot)
        except Exception as exc:  # noqa: BLE001 - counting must never break the summary
            logger.warning("snapshot verification failed case=%s: %s", case_id, exc)
            return 0
        return sum(1 for e in snapshots if e.payload_json.get("snapshot_hash") == current)

    async def _count_verified_reports(self, case_id: str, report_events: list) -> int:
        """Reports whose persisted canonical hash matches their ledger event."""
        if not report_events:
            return 0
        from app.repositories.report_repository import ReportRepository

        by_id = {row.id: row for row in await ReportRepository(self._session).list_by_case(int(case_id), limit=5000)}
        verified = 0
        for event in report_events:
            row = by_id.get(event.entity_id)
            if row is None:
                continue
            try:
                current = hash_report_payload(hashes.report_integrity_payload(
                    report_id=row.id, report_type=row.report_type, title=row.title,
                    sections=row.sections_json, generated_at=str(row.generated_at),
                ))
            except Exception:  # noqa: BLE001
                continue
            if current == event.payload_json.get("report_hash"):
                verified += 1
        return verified

    def _chain_status(self, case_id: str, chain: list) -> tuple[bool, str, list[str]]:
        if not chain:
            return False, "UNAVAILABLE", ["no ledger blocks exist for this case"]
        verification = self._engine.verify_chain(chain, self._engine.genesis_params(case_id))
        if verification.chain_valid:
            return True, "VALID", []
        if not verification.block_hashes_valid:
            return False, "MISMATCH", verification.issues
        return False, "WARNING", verification.issues

    async def _verify_stored_evidence(self, case_id: str, evidence: list) -> list[dict]:
        """Recompute content hashes from the authoritative case store (read-only)."""
        case_id = _normalize_case(case_id)
        sources = {s.source_id: s for s in await SourceRepository(self._session).list_by_case(int(case_id))}
        results: list[dict] = []
        for row in evidence:
            source = sources.get(row.source_id)
            if source is None:
                results.append(_evidence_verification(row, status="MISMATCH",
                                                      reason="source no longer exists in the case store"))
                continue
            try:
                current = await self._recompute_content_hash(case_id, source)
            except Exception as exc:  # noqa: BLE001 - treat as unverifiable
                logger.debug("evidence content hash recompute failed case=%s source=%s: %s",
                             case_id, source.source_id, exc)
                current = ""
            if current and current == row.content_hash:
                results.append(_evidence_verification(row, status="VERIFIED", reason="content hash matches"))
            else:
                results.append(_evidence_verification(
                    row, status="MISMATCH",
                    reason="current content hash differs from registered hash" if current else
                           "could not recompute current content hash"))
        return results

    async def _recompute_content_hash(self, case_id: str, source) -> str:
        case_id = _normalize_case(case_id)
        meta = source.metadata_json or {}
        records = [r for r in (meta.get("records") or []) if isinstance(r, dict)]
        return hash_evidence_payload(canonical_evidence_payload(
            case_id=case_id, source_id=source.source_id, source_type=source.source_type,
            filename=source.filename, records=records, text=str(meta.get("text") or ""),
        ))

    async def verify_case(self, case_id: str) -> dict:
        case_id = _normalize_case(case_id)
        chain = await self._store.get_chain(case_id)
        chain_valid, chain_status, issues = self._chain_status(case_id, chain)
        evidence = await EvidenceIntegrityRepository(self._session).list_by_case(case_id)
        checks = await self._verify_stored_evidence(case_id, evidence)
        mismatches = [c for c in checks if c["status"] == "MISMATCH"]

        # P1-5: verify every ledger event's payload hash + block reference, so
        # a modified payload or a dangling event->block pointer is detected.
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=5000)
        block_by_index = {block.index: block for block in chain}
        consistency_issues: list[dict] = []
        for event in events:
            issue = None
            computed = hash_json(event.payload_json or {})
            if event.payload_hash and computed != event.payload_hash:
                issue = "payload hash mismatch"
            elif event.block_index is not None:
                block = block_by_index.get(event.block_index)
                if block is None:
                    issue = "event references a missing block"
                elif event.block_hash and block.hash != event.block_hash:
                    issue = "event references a different block hash"
            if issue:
                consistency_issues.append({
                    "transaction_id": event.transaction_id,
                    "event_type": event.event_type,
                    "entity_id": event.entity_id,
                    "issue": issue,
                })

        return {
            "case_id": case_id,
            "chain_status": chain_status,
            "chain_valid": chain_valid,
            "blocks": len(chain),
            "evidence_checked": len(checks),
            "evidence_verified": sum(1 for c in checks if c["status"] == "VERIFIED"),
            "mismatches": mismatches[:50],
            "chain_issues": issues[:20],
            "events_checked": len(events),
            "event_consistency_valid": len(consistency_issues) == 0,
            "event_consistency_issues": consistency_issues[:50],
        }

    async def verify_evidence(self, case_id: str, source_id: str) -> dict:
        case_id = _normalize_case(case_id)
        repo = EvidenceIntegrityRepository(self._session)
        history = await repo.history_for_source(case_id, source_id)
        if not history:
            return {"case_id": case_id, "source_id": source_id, "verified": False,
                    "status": "UNAVAILABLE", "reason": "no integrity record for this source"}
        sources = {s.source_id: s for s in await SourceRepository(self._session).list_by_case(int(case_id))}
        source = sources.get(source_id)
        current = await self._recompute_content_hash(case_id, source) if source else ""
        versions = []
        latest_status = "MISMATCH"
        for row in history:
            ok = bool(current) and current == row.content_hash
            status = "VERIFIED" if ok else "MISMATCH"
            if row.version == history[-1].version:
                latest_status = status
            versions.append({
                "version": row.version, "status": status, "transaction_id": row.transaction_id,
                "block_index": row.block_index, "created_at": row.created_at.isoformat() if row.created_at else "",
            })
        return {
            "case_id": case_id, "source_id": source_id, "verified": latest_status == "VERIFIED",
            "status": latest_status, "versions": versions, "current_content_hash": current,
        }

    async def verify_record(self, case_id: str, source_id: str, record_id: str) -> dict:
        case_id = _normalize_case(case_id)
        source = None
        for s in await SourceRepository(self._session).list_by_case(int(case_id)):
            if s.source_id == source_id:
                source = s
                break
        if source is None:
            return {"verified": False, "status": "UNAVAILABLE", "reason": "source not found"}
        meta = source.metadata_json or {}
        records = [r for r in (meta.get("records") or []) if isinstance(r, dict)]
        entry = next((r for r in records if str(r.get("id", "")) == str(record_id)), None)
        if entry is None:
            return {"verified": False, "status": "UNAVAILABLE", "reason": "record not found"}

        current_hashes = [hashes.hash_canonical_record(r) for r in records]
        current_record_hash = hashes.hash_canonical_record(entry)
        current_root = merkle.merkle_root(current_hashes)

        # Committed canonical sha (captured at ingest time) guards against the
        # stored record dict drifting from what was actually processed.
        provenance = {str(p.get("record_id")): p for p in (meta.get("provenance") or [])}
        committed = provenance.get(str(record_id)) or {}
        committed_hash = committed.get("record_hash")
        if committed_hash and committed_hash != current_record_hash:
            return {
                "verified": False, "status": "MISMATCH",
                "reason": "current record content hash differs from its committed record hash",
                "record_hash": current_record_hash, "committed_record_hash": committed_hash,
            }

        # The COMMITTED batch (ledger) is the authority: the record's inclusion
        # proof must reconstruct the ROOT REGISTERED ON-CHAIN. We must not
        # silently accept a fresh root recomputed from a mutated record set.
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=2000)
        batch_event = next((e for e in events if e.event_type == "EVIDENCE_PROCESSED"
                            and e.entity_id == source_id and e.payload_json.get("merkle_root")), None)
        if batch_event is None:
            return {"verified": False, "status": "UNAVAILABLE",
                    "reason": "no ledger batch registration exists for this source"}
        committed_root = batch_event.payload_json.get("merkle_root")

        if current_root != committed_root:
            return {
                "verified": False, "status": "MISMATCH",
                "reason": "current record batch root differs from the committed ledger root "
                          "(batch contents changed)",
                "record_hash": current_record_hash,
                "current_merkle_root": current_root,
                "committed_merkle_root": committed_root,
            }

        proof = merkle.build_merkle_proof(current_record_hash, current_hashes)
        proof_valid = bool(proof) and merkle.verify_merkle_proof(proof, committed_root) if proof else False
        if not proof_valid:
            return {
                "verified": False, "status": "MISMATCH",
                "reason": "inclusion proof does not reconstruct the committed ledger root",
                "record_hash": current_record_hash,
                "committed_merkle_root": committed_root,
            }
        return {
            "verified": True,
            "status": "VERIFIED",
            "record_hash": current_record_hash,
            "merkle_root": committed_root,
            "record_count": len(records),
            "transaction_id": batch_event.transaction_id,
            "block_index": batch_event.block_index,
            "reason": "record hash is part of the registered batch (Merkle inclusion proof matches)",
            "merkle_proof": proof if proof_valid else None,
            "proof_valid": proof_valid,
        }

    async def get_case_ledger(self, case_id: str, limit: int = 200) -> list[dict]:
        case_id = _normalize_case(case_id)
        return [_block_read(b) for b in (await self._store.get_chain(case_id))[-limit:]]

    async def get_events(self, case_id: str, limit: int = 200) -> list[dict]:
        case_id = _normalize_case(case_id)
        return [_event_read(e) for e in await LedgerEventRepository(self._session).list_by_case(case_id, limit=limit)]

    async def get_transaction(self, case_id: str, transaction_id: str) -> dict | None:
        case_id = _normalize_case(case_id)
        event = await LedgerEventRepository(self._session).get_by_transaction(case_id, transaction_id)
        return _event_read(event) if event else None

    async def get_evidence_history(self, case_id: str, source_id: str) -> list[dict]:
        case_id = _normalize_case(case_id)
        rows = await EvidenceIntegrityRepository(self._session).history_for_source(case_id, source_id)
        return [self._evidence_read(row) for row in rows]

    async def pending_count(self, case_id: str) -> int:
        case_id = _normalize_case(case_id)
        pending = await IntegrityOutboxRepository(self._session).pending_for_case(case_id, limit=500)
        return len(pending)

    async def latest_event(self, case_id: str, event_type: str):
        case_id = _normalize_case(case_id)
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=200)
        for event in events:
            if event.event_type == event_type:
                return event
        return None

    async def verify_intelligence(self, case_id: str, current_snapshot_hash: str) -> dict:
        case_id = _normalize_case(case_id)
        event = await self.latest_event(case_id, "INTELLIGENCE_SNAPSHOT")
        if event is None:
            return {"verified": False, "status": "NOT_REGISTERED",
                    "reason": "no intelligence snapshot registration exists for this case"}
        registered = event.payload_json.get("snapshot_hash", "")
        matched = bool(current_snapshot_hash) and current_snapshot_hash == registered
        return {
            "verified": matched,
            "status": "VERIFIED" if matched else "MISMATCH",
            "current_snapshot_hash": current_snapshot_hash,
            "registered_snapshot_hash": registered,
            "transaction_id": event.transaction_id,
            "block_index": event.block_index,
        }

    async def verify_report(self, case_id: str, report_id: str, current_report_hash: str) -> dict:
        case_id = _normalize_case(case_id)
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=5000)
        event = next((e for e in events if e.event_type == "REPORT_GENERATED" and e.entity_id == report_id), None)
        if event is None:
            return {"verified": False, "status": "NOT_REGISTERED",
                    "reason": "report exists but no integrity registration was found"}
        registered = event.payload_json.get("report_hash", "")
        matched = bool(current_report_hash) and current_report_hash == registered
        return {
            "verified": matched,
            "status": "VERIFIED" if matched else "MISMATCH",
            "report_id": report_id,
            "current_report_hash": current_report_hash,
            "registered_report_hash": registered,
            "transaction_id": event.transaction_id,
            "block_index": event.block_index,
        }


def _block_read(block) -> dict | None:
    if block is None:
        return None
    return {
        "index": block.index,
        "timestamp": block.timestamp,
        "previous_hash": block.previous_hash,
        "data_hash": block.data_hash,
        "block_hash": block.hash,
        "case_id": block.case_id,
        "events": block.events,
    }


def _event_read(event) -> dict:
    return {
        "transaction_id": event.transaction_id,
        "case_id": event.case_id,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "payload_hash": event.payload_hash,
        "payload_json": event.payload_json or {},
        "block_index": event.block_index,
        "block_hash": event.block_hash,
        "previous_block_hash": event.previous_block_hash,
        "actor_id": event.actor_id,
        "status": event.status,
        "created_at": event.created_at.isoformat() if event.created_at else "",
    }


def _evidence_verification(row, status: str, reason: str) -> dict:
    return {
        "case_id": row.case_id,
        "source_id": row.source_id,
        "version": row.version,
        "registered_content_hash": row.content_hash,
        "status": status,
        "reason": reason,
        "transaction_id": row.transaction_id,
        "block_index": row.block_index,
    }


# Re-export statuses for routers/schemas.
CHAIN_STATUS_VALUES = CHAIN_STATUS
INTEGRITY_STATUS_VALUES = INTEGRITY_STATUS
OUTBOX_STATUS_VALUES = OUTBOX_STATUS