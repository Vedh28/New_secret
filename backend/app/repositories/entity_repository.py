"""Repository for extracted entities + relationships (Phase 2)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity, EntityRelationship
from app.repositories.base import BaseRepository


class EntityRepository(BaseRepository[Entity]):
    """Async repository for per-case extracted entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Entity)

    async def get(self, case_id: int, entity_id: str, entity_type: str) -> Entity | None:
        stmt = (
            select(Entity)
            .where(Entity.case_id == case_id, Entity.entity_id == entity_id,
                   Entity.entity_type == entity_type)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_any_type(self, case_id: int, entity_id: str) -> Entity | None:
        """Find a canonical entity by its stable external id."""
        stmt = (
            select(Entity)
            .where(Entity.case_id == case_id, Entity.entity_id == entity_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_case(self, case_id: int) -> list[Entity]:
        stmt = select(Entity).where(Entity.case_id == case_id).order_by(Entity.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class RelationshipRepository(BaseRepository[EntityRelationship]):
    """Async repository for per-case extracted relationships."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EntityRelationship)

    async def get(self, case_id: int, rel_type: str, source_id: str, target_id: str) -> EntityRelationship | None:
        stmt = (
            select(EntityRelationship)
            .where(EntityRelationship.case_id == case_id,
                   EntityRelationship.rel_type == rel_type,
                   EntityRelationship.source_id == source_id,
                   EntityRelationship.target_id == target_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_case(self, case_id: int) -> list[EntityRelationship]:
        stmt = select(EntityRelationship).where(EntityRelationship.case_id == case_id).order_by(EntityRelationship.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
