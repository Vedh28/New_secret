"""Potential-link analyst decision repository (P1.3, hardened)."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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

    async def upsert_pair(self, *, case_id: int, entity_a: str, entity_b: str,
                          new_status: str, decision: str, analyst_id: int | None,
                          evidence_ids: list[str], notes: str | None) -> PotentialLinkDecision:
        """Database-atomic upsert keyed by UNIQUE(case_id, entity_a, entity_b).

        Concurrent requests for the same pair collapse onto ONE row: INSERT
        wins, the loser becomes an UPDATE that advances `previous_status` from
        the row's CURRENT new_status (self-reference) to the new value. Latest
        successful write wins. No IntegrityError is surfaceable from a normal
        race; the unique constraint remains the final backstop.
        """
        table = PotentialLinkDecision.__table__
        values = {
            "case_id": case_id,
            "entity_a": entity_a,
            "entity_b": entity_b,
            "new_status": new_status,
            "decision": decision,
            "analyst_id": analyst_id,
            "evidence_ids": evidence_ids,
            "notes": notes,
            "previous_status": "POTENTIAL",
        }
        # Select the dialect-appropriate upsert. Both expose the same
        # on_conflict_do_update API.
        dialect = self._session.get_bind().dialect.name
        insert_stmt = (pg_insert(table) if dialect == "postgresql" else sqlite_insert(table))
        stmt = insert_stmt.values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.case_id, table.c.entity_a, table.c.entity_b],
            set_={
                "previous_status": table.c.new_status,  # auto-advance: old -> new
                "new_status": new_status,
                "decision": decision,
                "analyst_id": analyst_id,
                "evidence_ids": evidence_ids,
                "notes": notes,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()
        row = await self.get_pair(case_id, entity_a, entity_b)
        if row is None:  # pragma: no cover - defensive; upsert should have created it
            row = await super().create(**values, new_status=new_status)
        return row

    async def list_by_case(self, case_id: int, limit: int = 100) -> list[PotentialLinkDecision]:
        stmt = (
            select(PotentialLinkDecision)
            .where(PotentialLinkDecision.case_id == case_id)
            .order_by(PotentialLinkDecision.created_at.desc(), PotentialLinkDecision.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())