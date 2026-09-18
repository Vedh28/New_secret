"""Default SIH adapter: LocalPermissionedLedger persisted in PostgreSQL.

The chain ENGINE stays pure; this adapter persists the generated blocks into
the `ledger_blocks` table so the integrity chain survives restarts. Every read
is case-scoped.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.interface import Block, IntegrityEventStore
from app.blockchain.local_ledger import LocalPermissionedLedger
from app.repositories.integrity_repository import LedgerBlockRepository


class LocalLedgerStore(IntegrityEventStore):
    """PostgreSQL-backed persistence for the local permissioned ledger."""

    def __init__(self, session: AsyncSession, engine: LocalPermissionedLedger | None = None) -> None:
        self._session = session
        self._engine = engine or LocalPermissionedLedger()

    async def append_block(self, block: Block) -> Block:
        repo = LedgerBlockRepository(self._session)
        await repo.create(
            case_id=block.case_id,
            index=block.index,
            timestamp_iso=block.timestamp,
            previous_hash=block.previous_hash,
            data_hash=block.data_hash,
            block_hash=block.hash,
            events_json=block.events,
        )
        return block

    async def get_chain(self, case_id: str) -> list[Block]:
        rows = await LedgerBlockRepository(self._session).chain(case_id)
        return [
            Block(
                index=row.index,
                timestamp=row.timestamp_iso,
                previous_hash=row.previous_hash,
                data_hash=row.data_hash,
                hash=row.block_hash,
                case_id=row.case_id,
                events=row.events_json or [],
            )
            for row in rows
        ]

    async def latest_block(self, case_id: str) -> Block | None:
        row = await LedgerBlockRepository(self._session).latest(case_id)
        if row is None:
            return None
        return Block(
            index=row.index,
            timestamp=row.timestamp_iso,
            previous_hash=row.previous_hash,
            data_hash=row.data_hash,
            hash=row.block_hash,
            case_id=row.case_id,
            events=row.events_json or [],
        )


def get_ledger_engine():
    """Return the configured chain engine (local by default)."""
    from app.core.config import get_settings

    provider = get_settings().blockchain_provider or "local"
    if provider == "evm":
        from app.blockchain.adapters.evm import EvmBlockchainAdapter
        return EvmBlockchainAdapter()
    return LocalPermissionedLedger()