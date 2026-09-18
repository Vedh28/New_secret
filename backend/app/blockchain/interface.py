"""Blockchain ledger abstraction (Phase 1).

SECRET depends on the `BlockchainLedger` interface, not on any vendor SDK.
Concrete adapters (`LocalPermissionedLedger`, future EVM adapter) implement the
same small contract. The ledger stores integrity references and hashes only —
never raw evidence.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Block:
    """One chained ledger block (permissioned integrity chain, per case)."""

    index: int
    timestamp: str                       # ISO-8601 (UTC)
    previous_hash: str
    data_hash: str                        # aggregate of this block's events
    hash: str
    case_id: str = ""
    events: list[dict] = field(default_factory=list)   # non-sensitive event refs


@dataclass
class ChainVerification:
    """Factual integrity checks over a chain."""

    chain_valid: bool
    blocks: int
    issues: list[str] = field(default_factory=list)
    previous_hashes_valid: bool = True
    block_hashes_valid: bool = True
    genesis_valid: bool = True


class BlockchainLedger(ABC):
    """Application-facing ledger contract."""

    @abstractmethod
    def genesis_params(self, case_id: str) -> dict:
        """Return deterministic genesis parameters for a case chain."""

    @abstractmethod
    def compute_block(self, *, previous: Block | None, case_id: str,
                      events: list[dict]) -> Block:
        """Build the next chained block over `events` (pure, deterministic)."""

    @abstractmethod
    def verify_chain(self, blocks: list[Block], genesis_params: dict) -> ChainVerification:
        """Validate genesis, previous-hash links and recomputed block hashes."""


class IntegrityEventStore(ABC):
    """Persistence contract for ledger blocks (PostgreSQL-backed)."""

    @abstractmethod
    async def append_block(self, block: Block) -> Block:
        """Persist a block for its case chain."""

    @abstractmethod
    async def get_chain(self, case_id: str) -> list[Block]:
        """Return the full ordered chain for ONE case."""

    @abstractmethod
    async def latest_block(self, case_id: str) -> Block | None:
        """Return the newest block for a case, if any."""