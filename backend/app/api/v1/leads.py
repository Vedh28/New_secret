"""Investigative lead endpoints (Phase 12)."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, RequireAnalyst
from app.schemas.lead import LeadCreate, LeadRead, LeadUpdate
from app.services.lead_service import LeadService

router = APIRouter()


def _to_read(lead) -> LeadRead:
    return LeadRead(
        id=lead.id,
        case_id=lead.case_id,
        kind=lead.kind,
        title=lead.title,
        description=lead.description,
        priority=lead.priority,
        info_gain=lead.info_gain,
        status=lead.status,
        entity_ids=lead.entity_ids,
        evidence_ids=lead.evidence_ids,
        recommended_action=lead.recommended_action,
        recommended_source=lead.recommended_source,
        explanation=lead.explanation,
        notes=lead.notes,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


@router.get("/{case_key}/leads", response_model=list[LeadRead], summary="List investigative leads")
async def list_leads(case_key: str, session: DbSession, _user: CurrentUser) -> list[LeadRead]:
    return [_to_read(l) for l in await LeadService(session).list(case_key)]


@router.post(
    "/{case_key}/leads",
    response_model=LeadRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an investigative lead (hypothesis)",
)
async def create_lead(case_key: str, payload: LeadCreate, session: DbSession, user: CurrentUser) -> LeadRead:
    lead = await LeadService(session).create(case_key, payload, user.id)
    await _audit_lead(session, user, "lead_created", lead, {"case_key": case_key, "status": lead.status, "kind": lead.kind})
    await session.commit()
    await session.refresh(lead)
    return _to_read(lead)


@router.patch(
    "/{case_key}/leads/{lead_id}",
    response_model=LeadRead,
    summary="Update lead status / notes",
)
async def update_lead(
    case_key: str, lead_id: int, payload: LeadUpdate, session: DbSession, user: CurrentUser
) -> LeadRead:
    lead = await LeadService(session).update(case_key, lead_id, payload, user.id)
    await _audit_lead(session, user, "lead_updated", lead, {"case_key": case_key, "status": lead.status, "notes": payload.notes})
    await session.commit()
    await session.refresh(lead)
    return _to_read(lead)


async def _audit_lead(session, user, action: str, lead, result: dict) -> None:
    """Best-effort audit write for lead lifecycle actions."""
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            user, action, object_type="lead", object_id=str(lead.id), result=result
        )
    except Exception as exc:  # noqa: BLE001 - best-effort audit
        import logging
        logging.getLogger("secret.audit").warning(
            "lead audit failed lead=%s action=%s type=%s",
            getattr(lead, "id", None), action, type(exc).__name__)