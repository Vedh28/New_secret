"""Potential-link analyst decision repository (P1.3)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.link_decision import PotentialLinkDecision
from app.repositories.base import BaseRepository


class LinkDecisionRepository(BaseRepository[PotentialLinkDecision]):
    """Async repository for potential-link analyst decisions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PotentialLinkDecision)

    async def get_pair(self, case_id: int, entity_a: str, entity_b: str) -> PotentialLinkDecision | None:
        stmt = (
            select(PotentialLinkDecision)
            .where(
                PotentialLinkDecision.case_id == case_id,
                PotentialLinkDecision.entity_a == entity_a,
                PotentialLinkDecision.entity_b == entity_b,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_case(self, case_id: int, limit: int = 100) -> list[PotentialLinkDecision]:
        stmt = (
            select(PotentialLinkDecision)
            .where(PotentialLinkDecision.case_id == case_id)
            .order_by(PotentialLinkDecision.created_at.desc(), PotentialLinkDecision.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())