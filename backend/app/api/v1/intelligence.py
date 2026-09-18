"""Case intelligence endpoints (Phase 15).

Expose the unified intelligence layer: full case intelligence, hidden links,
network DNA, leads, and what-if simulation. Results are analytical — decision
support, never a guilt finding.
"""
from __future__ import annotations

import networkx as nx
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, RequireAnalyst
from app.repositories.case_repository import CaseRepository
from app.schemas.link_decision import LinkDecisionCreate, LinkDecisionRead
from app.services.audit_service import AuditService
from app.services.case_intelligence_service import CaseIntelligenceService
from app.intelligence import simulate
from app.repositories.link_decision_repository import LinkDecisionRepository
from app.models.link_decision import LINK_STATUSES

router = APIRouter()

# Per-process cache of computed intelligence per case id.
_cache: dict[int, dict] = {}


def invalidate_case_cache(case_id: int) -> None:
    """Drop stale intelligence for a case after its data changes (ingestion)."""
    _cache.pop(case_id, None)


def clear_cache() -> None:
    """Drop all cached intelligence (test isolation / case bulk changes)."""
    _cache.clear()


def _d(dataclass_obj) -> dict:
    from dataclasses import asdict
    return asdict(dataclass_obj)


async def _resolve_case_id(session, case_key: str) -> int:
    repo = CaseRepository(session)
    case = await repo.get_by_case_number(case_key)
    if case is not None:
        return case.id
    if case_key.isdigit():
        c = await repo.get(int(case_key))
        if c is not None:
            return c.id
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


@router.get("/{case_key}/intelligence", summary="Full unified case intelligence")
async def get_intelligence(case_key: str, session: DbSession, _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    return await CaseIntelligenceService(session).build(case_id, cache=_cache)


@router.get("/{case_key}/hidden-links", summary="Potential / hidden link discovery")
async def hidden_links(case_key: str, session: DbSession, _user: CurrentUser) -> list[dict]:
    case_id = await _resolve_case_id(session, case_key)
    result = await CaseIntelligenceService(session).build(case_id, cache=_cache)
    return result["potential_links"]  # already serialized by the unified service


@router.get("/{case_key}/network-dna", summary="Network analytical fingerprint")
async def network_dna(case_key: str, session: DbSession, _user: CurrentUser) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    result = await CaseIntelligenceService(session).build(case_id, cache=_cache)
    return result["network_dna"]


@router.post("/{case_key}/simulate", summary="What-if investigation simulation")
async def what_if(
    case_key: str,
    payload: dict,
    session: DbSession,
    _user: CurrentUser,
) -> dict:
    case_id = await _resolve_case_id(session, case_key)
    op = payload.get("operation")
    subject = payload.get("subject")
    if op not in ("remove_entity", "remove_relationship", "add_relationship", "confirm_potential", "hide_entity"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid operation")
    if not subject:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="subject required")

    # Build the current graph from persisted entities/relationships.
    data = await _load_case_data(session, case_id)
    graph = nx.Graph()
    for e in data.entities:
        graph.add_node(e.id, type=e.type, name=e.name)
    for r in data.relationships:
        graph.add_edge(r.source, r.target, type=r.rel_type, weight=r.strength or r.confidence)

    result = simulate.simulate(graph, op, subject)
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            _user, "simulation_executed", object_type="simulation", object_id=subject,
            result={"case_id": case_id, "operation": op},
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        pass
    return _d(result)


async def _load_case_data(session, case_id):
    from app.repositories.case_analytics_repo import build_case_data
    return await build_case_data(session, case_id)


_DECISION_TO_STATUS = {
    "CONFIRM": "ANALYST_CONFIRMED",
    "REJECT": "REJECTED",
    "DEFER": "DEFERRED",
}


@router.get(
    "/{case_key}/potential-links/decisions",
    response_model=list[LinkDecisionRead],
    summary="Analyst decisions on potential relationships",
)
async def list_decisions(case_key: str, session: DbSession, _user: CurrentUser) -> list[LinkDecisionRead]:
    case_id = await _resolve_case_id(session, case_key)
    repo = LinkDecisionRepository(session)
    return [_decision_read(d) for d in await repo.list_by_case(case_id)]


@router.post(
    "/{case_key}/potential-links/decision",
    response_model=LinkDecisionRead,
    summary="Record an analyst CONFIRM / REJECT / DEFER decision",
)
async def record_decision(
    case_key: str,
    payload: LinkDecisionCreate,
    session: DbSession,
    user: CurrentUser,
    _act: RequireAnalyst,
) -> LinkDecisionRead:
    case_id = await _resolve_case_id(session, case_key)
    repo = LinkDecisionRepository(session)
    a, b = sorted([payload.source, payload.target])
    existing = await repo.get_pair(case_id, a, b)
    previous = existing.new_status if existing else "POTENTIAL"
    new_status = _DECISION_TO_STATUS[payload.decision]

    if existing is None:
        decision = await repo.create(
            case_id=case_id,
            entity_a=a,
            entity_b=b,
            previous_status=previous,
            new_status=new_status,
            decision=payload.decision,
            analyst_id=user.id,
            evidence_ids=payload.evidence_ids,
            notes=payload.notes,
        )
    else:
        existing.previous_status = previous
        existing.new_status = new_status
        existing.decision = payload.decision
        existing.analyst_id = user.id
        existing.evidence_ids = payload.evidence_ids
        existing.notes = payload.notes
        decision = await repo.save(existing)

    await AuditService(session).record(
        user=user,
        action=f"potential_link_{payload.decision.lower()}",
        object_type="potential_link",
        object_id=f"{a}<->{b}",
        result={
            "case_id": case_id,
            "previous_status": previous,
            "new_status": new_status,
            "evidence_ids": payload.evidence_ids,
        },
    )
    invalidate_case_cache(case_id)
    await session.commit()
    await session.refresh(decision)
    return _decision_read(decision)


def _decision_read(d) -> LinkDecisionRead:
    return LinkDecisionRead(
        id=d.id,
        case_id=d.case_id,
        entity_a=d.entity_a,
        entity_b=d.entity_b,
        previous_status=d.previous_status,
        new_status=d.new_status,
        decision=d.decision,
        analyst_id=d.analyst_id,
        evidence_ids=d.evidence_ids,
        notes=d.notes,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )