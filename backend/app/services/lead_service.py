"""Investigative lead service (Phase 12)."""
from fastapi import HTTPException, status

from app.models.lead import Lead
from app.repositories.case_repository import CaseRepository
from app.repositories.lead_repository import LeadRepository


class LeadService:
    """CRUD for investigative leads (hypotheses derived from analytics)."""

    def __init__(self, session) -> None:
        self._leads = LeadRepository(session)
        self._cases = CaseRepository(session)

    async def _resolve_case_id(self, case_key: str) -> int:
        case = await self._cases.get_by_case_number(case_key)
        if case is not None:
            return case.id
        if case_key.isdigit():
            c = await self._cases.get(int(case_key))
            if c is not None:
                return c.id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    async def list(self, case_key: str) -> list[Lead]:
        case_id = await self._resolve_case_id(case_key)
        return await self._leads.list_by_case(case_id)

    async def create(self, case_key: str, payload, user_id: int | None) -> Lead:
        case_id = await self._resolve_case_id(case_key)
        return await self._leads.create(
            case_id=case_id,
            kind=payload.kind,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            info_gain=payload.info_gain,
            status=payload.status,  # canonical hypothesis status (default POTENTIAL)
            entity_ids=payload.entity_ids,
            evidence_ids=payload.evidence_ids,
            recommended_action=payload.recommended_action,
            recommended_source=payload.recommended_source,
            explanation=payload.explanation,
            created_by_id=user_id,
        )

    async def update(self, case_key: str, lead_id: int, payload, user_id: int | None) -> Lead:
        case_id = await self._resolve_case_id(case_key)
        lead = await self._leads.get(lead_id)
        if lead is None or lead.case_id != case_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
        if payload.status is not None:
            lead.status = payload.status
        if payload.notes is not None:
            lead.notes = payload.notes
        if payload.description is not None:
            lead.description = payload.description
        lead = await self._leads.save(lead)
        return lead