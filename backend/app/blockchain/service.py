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

        Returns [{outbox_id, transaction_id, block_index}] for confirmed
        appends. On any ledger failure, marks pending rows FAILED (retryable)
        and returns [] — never raises into the investigation pipeline.
        """
        case_id = _normalize_case(case_id)
        pending = await IntegrityOutboxRepository(self._session).pending_for_case(case_id, limit=max_events)
        if not pending:
            return []

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
        except Exception as exc:  # noqa: BLE001 - integrity failure must not break case work
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
        """Register one batched RECORD_BATCH / PROCESSED integrity event."""
        case_id = _normalize_case(case_id)
        record_hashes = [hashes.hash_record(_canonical_record(record)) for record in records]
        batch = merkle.batch_integrity(record_hashes) if record_hashes else None

        payload = {
            "event_type": "EVIDENCE_PROCESSED",
            "case_id": str(case_id),
            "source_id": str(source_id),
            "source_type": str(source_type or ""),
            "record_count": len(records),
            "merkle_root": batch["merkle_root"] if batch else None,
            "batch_algorithm": "MERKLE-SHA256" if batch else None,
            "entities_extracted": (extraction or {}).get("entities", 0),
            "relationships_extracted": (extraction or {}).get("relationships", 0),
            "actor_id": str(actor_id or ""),
        }
        outcome = await self._append_and_link(
            case_id=case_id, event_type="EVIDENCE_PROCESSED", entity_type="source",
            entity_id=source_id, payload=payload, actor_id=actor_id,
        )
        if batch and outcome.get("transaction_id"):
            extra = {
                "event_type": "RECORD_BATCH_REGISTERED",
                "case_id": str(case_id),
                "source_id": str(source_id),
                "record_count": len(records),
                "merkle_root": batch["merkle_root"],
                "batch_algorithm": "MERKLE-SHA256",
                "actor_id": str(actor_id or ""),
            }
            await self.enqueue(case_id=case_id, event_type="RECORD_BATCH_REGISTERED",
                               entity_type="source", entity_id=source_id,
                               payload=extra, actor_id=actor_id)
        return {**payload, "merkle_root": batch["merkle_root"] if batch else None}

    # ------------------------------------------------------------------
    # Analyst decision integrity (Phase 12)
    # ------------------------------------------------------------------
    async def record_analyst_decision(self, *, case_id: str, entity_a: str, entity_b: str,
                                      decision: str, evidence_ids: list[str], notes: str | None,
                                      actor_id: int | None, snapshot_hash: str = "") -> dict:
        case_id = _normalize_case(case_id)
        payload = hash_decision_payload(
            case_id=case_id, entity_a=entity_a, entity_b=entity_b, decision=decision,
            evidence_ids_hash=hash_json(sorted(evidence_ids or [])),
            notes_hash=hash_text(notes or ""), analyst_id=actor_id, snapshot_hash=snapshot_hash,
        )
        payload["event_type"] = "ANALYST_DECISION"
        outcome = await self._append_and_link(
            case_id=case_id, event_type="ANALYST_DECISION",
            entity_type="potential_link", entity_id=f"{entity_a}<->{entity_b}",
            payload=payload, actor_id=actor_id,
        )
        return {**payload, "transaction_id": outcome.get("transaction_id"), "block_index": outcome.get("block_index")}

    # ------------------------------------------------------------------
    # Intelligence snapshot integrity (Phase 11)
    # ------------------------------------------------------------------
    async def register_intelligence_snapshot(self, *, case_id: str, snapshot: dict,
                                             actor_id: int | None = None) -> dict:
        case_id = _normalize_case(case_id)
        snapshot_hash = hash_intelligence_snapshot(snapshot)
        payload = {
            "event_type": "INTELLIGENCE_SNAPSHOT",
            "case_id": str(case_id),
            "engine": "CaseIntelligenceService",
            "engine_version": "1.x",
            "snapshot_hash": snapshot_hash,
            "created_at": _now_iso(),
            "actor_id": str(actor_id or ""),
        }
        outcome = await self._append_and_link(
            case_id=case_id, event_type="INTELLIGENCE_SNAPSHOT",
            entity_type="case", entity_id=str(case_id), payload=payload, actor_id=actor_id,
        )
        return {**payload, "transaction_id": outcome.get("transaction_id"), "block_index": outcome.get("block_index")}

    # ------------------------------------------------------------------
    # Report integrity (Phase 13)
    # ------------------------------------------------------------------
    async def register_report(self, *, case_id: str, report: Any, actor_id: int | None = None) -> dict:
        case_id = _normalize_case(case_id)
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

        events = await events_repo.list_by_case(case_id, limit=1)
        snapshots = [e for e in events if e.event_type == "INTELLIGENCE_SNAPSHOT"]
        reports = [e for e in events if e.event_type == "REPORT_GENERATED"]

        latest_block = chain[-1] if chain else None
        return {
            "case_id": case_id,
            "chain_status": chain_status,
            "chain_valid": chain_valid,
            "blocks": len(chain),
            "events": await events_repo.count_by_case(case_id),
            "evidence_registered": registered,
            "evidence_verified": verified,
            "mismatches": mismatches,
            "verified_snapshots": len(snapshots),
            "verified_reports": len(reports),
            "latest_block": _block_read(latest_block),
            "issues": issues[:10],
        }

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
            except Exception:  # noqa: BLE001
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
        return {
            "case_id": case_id,
            "chain_status": chain_status,
            "chain_valid": chain_valid,
            "blocks": len(chain),
            "evidence_checked": len(checks),
            "evidence_verified": sum(1 for c in checks if c["status"] == "VERIFIED"),
            "mismatches": mismatches[:50],
            "chain_issues": issues[:20],
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
        record_hashes = [hashes.hash_record(_canonical_record(r)) for r in records]
        record_hash = hashes.hash_record(_canonical_record(entry))
        root = merkle.merkle_root(record_hashes)
        batch = merkle.batch_integrity(record_hashes)
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=500)
        batch_event = next((e for e in events if e.event_type == "EVIDENCE_PROCESSED" and e.entity_id == source_id
                            and e.payload_json.get("merkle_root") == root), None)
        if batch_event is None:
            return {"verified": False, "status": "UNAVAILABLE",
                    "reason": "no ledger batch found for this source's record set"}
        return {
            "verified": True,
            "status": "VERIFIED",
            "record_hash": record_hash,
            "merkle_root": root,
            "record_count": len(records),
            "transaction_id": batch_event.transaction_id,
            "block_index": batch_event.block_index,
            "reason": "record hash is part of the registered batch root",
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
            return {"verified": False, "status": "UNAVAILABLE",
                    "reason": "no intelligence snapshot registered for this case"}
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
        events = await LedgerEventRepository(self._session).list_by_case(case_id, limit=500)
        event = next((e for e in events if e.event_type == "REPORT_GENERATED" and e.entity_id == report_id), None)
        if event is None:
            return {"verified": False, "status": "UNAVAILABLE",
                    "reason": "no integrity event registered for this report"}
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


def _canonical_record(record: dict) -> dict:
    """Normalize a stored record for deterministic hashing."""
    fields = record.get("fields") or {}
    return {
        "id": str(record.get("id", "")),
        "source_type": str(record.get("source_type", "")),
        "timestamp": str(record.get("timestamp", "")),
        "fields": {k: v for k, v in sorted((fields or {}).items())},
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