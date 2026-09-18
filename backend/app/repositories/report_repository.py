"""Report repository (P0.2, PostgreSQL-persisted reports)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository[Report]):
    """Async repository for persisted reports."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Report)

    async def get_by_case_and_id(self, case_id: int, report_id: str) -> Report | None:
        stmt = (
            select(Report)
            .where(Report.id == report_id, Report.case_id == case_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_case(self, case_id: int, limit: int = 100) -> list[Report]:
        stmt = (
            select(Report)
            .where(Report.case_id == case_id)
            .order_by(Report.generated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(self, limit: int = 100) -> list[Report]:
        stmt = (
            select(Report)
            .order_by(Report.generated_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())