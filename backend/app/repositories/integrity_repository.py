"""Repositories for block integrity models (integrity layer)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integrity import EvidenceIntegrity, IntegrityOutbox, LedgerBlock, LedgerEvent
from app.repositories.base import BaseRepository


class LedgerBlockRepository(BaseRepository[LedgerBlock]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LedgerBlock)

    async def latest(self, case_id: str) -> LedgerBlock | None:
        stmt = (
            select(LedgerBlock)
            .where(LedgerBlock.case_id == case_id)
            .order_by(LedgerBlock.index.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_case_and_index(self, case_id: str, index: int) -> LedgerBlock | None:
        stmt = (
            select(LedgerBlock)
            .where(LedgerBlock.case_id == case_id, LedgerBlock.index == index)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def chain(self, case_id: str) -> list[LedgerBlock]:
        stmt = (
            select(LedgerBlock)
            .where(LedgerBlock.case_id == case_id)
            .order_by(LedgerBlock.index.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class LedgerEventRepository(BaseRepository[LedgerEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LedgerEvent)

    async def list_by_case(self, case_id: str, limit: int = 200, offset: int = 0) -> list[LedgerEvent]:
        stmt = (
            select(LedgerEvent)
            .where(LedgerEvent.case_id == case_id)
            .order_by(LedgerEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_transaction(self, case_id: str, transaction_id: str) -> LedgerEvent | None:
        stmt = (
            select(LedgerEvent)
            .where(LedgerEvent.case_id == case_id, LedgerEvent.transaction_id == transaction_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class EvidenceIntegrityRepository(BaseRepository[EvidenceIntegrity]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EvidenceIntegrity)

    async def list_by_case(self, case_id: str) -> list[EvidenceIntegrity]:
        stmt = (
            select(EvidenceIntegrity)
            .where(EvidenceIntegrity.case_id == case_id)
            .order_by(EvidenceIntegrity.source_id, EvidenceIntegrity.version.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def latest_for_source(self, case_id: str, source_id: str) -> EvidenceIntegrity | None:
        stmt = (
            select(EvidenceIntegrity)
            .where(EvidenceIntegrity.case_id == case_id, EvidenceIntegrity.source_id == source_id)
            .order_by(EvidenceIntegrity.version.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def history_for_source(self, case_id: str, source_id: str) -> list[EvidenceIntegrity]:
        stmt = (
            select(EvidenceIntegrity)
            .where(EvidenceIntegrity.case_id == case_id, EvidenceIntegrity.source_id == source_id)
            .order_by(EvidenceIntegrity.version.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class IntegrityOutboxRepository(BaseRepository[IntegrityOutbox]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IntegrityOutbox)

    async def pending_for_case(self, case_id: str, limit: int = 200) -> list[IntegrityOutbox]:
        stmt = (
            select(IntegrityOutbox)
            .where(IntegrityOutbox.case_id == case_id, IntegrityOutbox.status.in_(("PENDING", "FAILED")))
            .order_by(IntegrityOutbox.id.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def failed_for_case(self, case_id: str, limit: int = 100) -> list[IntegrityOutbox]:
        stmt = (
            select(IntegrityOutbox)
            .where(IntegrityOutbox.case_id == case_id, IntegrityOutbox.status == "FAILED")
            .order_by(IntegrityOutbox.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())