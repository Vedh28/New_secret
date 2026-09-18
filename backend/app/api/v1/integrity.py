"""Evidence integrity / blockchain ledger endpoints (integrity layer).

All endpoints are case-scoped and RBAC-protected. Only hashes + references are
exposed — never raw evidence, notes or PII. Verification is factual: a
"VERIFIED" value means the current content matches its registered hash.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, RequireAnalyst
from app.repositories.case_repository import CaseRepository
from app.blockchain.service import BlockchainIntegrityService

router = APIRouter()


async def _resolve_case_id(session, case_key: str) -> int:
    repo = CaseRepository(session)
    case = await repo.get_by_case_number(case_key)
    if case is not None:
        return case.id
    if case_key.isdigit():
        case = await repo.get(int(case_key))
        if case is not None:
            return case.id
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


async def _service(session) -> BlockchainIntegrityService:
    return BlockchainIntegrityService(session)


@router.get("/{case_key}", summary="Case integrity ledger summary")
async def case_integrity(case_key: str, session: DbSession, _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    return await (await _service(session)).case_summary(case_id)


@router.get("/{case_key}/events", summary="Case integrity events (chain of custody)")
async def case_events(case_key: str, session: DbSession, _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    return {
        "case_id": case_id,
        "events": await svc.get_events(case_id),
        "pending": await svc.pending_count(case_id),
    }


@router.get("/{case_key}/evidence/{source_id}", summary="Evidence integrity status")
async def evidence_integrity(case_key: str, source_id: str, session: DbSession,
                             _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    return await (await _service(session)).verify_evidence(case_id, source_id)


@router.get("/{case_key}/evidence/{source_id}/history", summary="Evidence version history")
async def evidence_history(case_key: str, source_id: str, session: DbSession,
                           _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    return {
        "case_id": case_id,
        "source_id": source_id,
        "versions": await (await _service(session)).get_evidence_history(case_id, source_id),
    }


@router.get("/{case_key}/transactions/{transaction_id}", summary="Look up one ledger transaction")
async def get_transaction(case_key: str, transaction_id: str, session: DbSession,
                          _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    event = await (await _service(session)).get_transaction(case_id, transaction_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return event


@router.get("/{case_key}/ledger", summary="Full chained ledger blocks for a case")
async def case_ledger(case_key: str, session: DbSession, _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    return {"case_id": case_id, "blocks": await svc.get_case_ledger(case_id)}


@router.post("/{case_key}/verify", summary="Verify the full case integrity chain", status_code=200)
async def verify_case(case_key: str, session: DbSession, user: RequireAnalyst) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    await svc.flush_pending(case_id)  # confirm pending events first
    await session.commit()
    return await svc.verify_case(case_id)


@router.post("/{case_key}/verify/evidence/{source_id}", summary="Verify one evidence source")
async def verify_evidence(case_key: str, source_id: str, session: DbSession,
                          user: RequireAnalyst) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    await svc.flush_pending(case_id)
    await session.commit()
    return await svc.verify_evidence(case_id, source_id)


@router.post("/{case_key}/verify/record/{source_id}/{record_id}", summary="Verify one record against its batch Merkle root")
async def verify_record(case_key: str, source_id: str, record_id: str, session: DbSession,
                        user: RequireAnalyst) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    await svc.flush_pending(case_id)
    await session.commit()
    return await svc.verify_record(case_id, source_id, record_id)


@router.post("/{case_key}/verify/report/{report_id}", summary="Verify a generated report's registered hash")
async def verify_report(case_key: str, report_id: str, session: DbSession,
                        user: RequireAnalyst) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    await svc.flush_pending(case_id)
    await session.commit()

    from app.blockchain.hashes import hash_report_payload, report_integrity_payload
    from app.reports.service import _STORE

    report = _STORE.get(report_id)
    if report is None:
        return {"verified": False, "status": "UNAVAILABLE", "reason": "report is not in the process store"}
    current_hash = hash_report_payload(report_integrity_payload(
        report_id=report.id, report_type=report.report_type, title=report.title,
        sections=list(report.sections), generated_at=str(report.generated_at),
    ))
    return await svc.verify_report(case_id, report_id, current_hash)


@router.post("/{case_key}/verify/intelligence", summary="Verify the latest intelligence snapshot hash")
async def verify_intelligence(case_key: str, session: DbSession, user: RequireAnalyst) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    svc = await _service(session)
    await svc.flush_pending(case_id)
    await session.commit()

    from app.services.case_intelligence_service import CaseIntelligenceService
    # REBUILD WITHOUT registering a new snapshot (no infinite loop) and WITHOUT
    # cache so we verify the current persisted state, not a stale snapshot.
    snapshot = await CaseIntelligenceService(session).build(case_id, cache={}, register_integrity=False)
    from app.blockchain.hashes import hash_intelligence_snapshot
    current_hash = hash_intelligence_snapshot(snapshot)
    return await svc.verify_intelligence(case_id, current_hash)