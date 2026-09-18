"""Blockchain / evidence integrity ORM models (integrity layer).

The ledger records cryptographic references only. PostgreSQL keeps the
authoritative operational data; these tables persist the chained blocks, the
mapped ledger events, per-source evidence versions and the integrity OUTBOX
(which decouples business commits from ledger appends).

Every row is case-scoped — cross-case queries never happen.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_types import BigSerialId, JsonType

# Ledger / integrity status vocabulary (shared, single source of truth).
INTEGRITY_STATUS = ("REGISTERED", "PENDING", "VERIFIED", "MISMATCH", "LEDGER_UNAVAILABLE")
OUTBOX_STATUS = ("PENDING", "CONFIRMED", "FAILED")
CHAIN_STATUS = ("VALID", "WARNING", "MISMATCH", "UNAVAILABLE")

# Canonical integrity event types (chain-of-custody vocabulary).
EVENT_TYPES = (
    "EVIDENCE_REGISTERED",
    "EVIDENCE_PROCESSED",
    "EVIDENCE_VERSION_CREATED",
    "RECORD_BATCH_REGISTERED",
    "ENTITY_EXTRACTED",
    "RELATIONSHIP_DERIVED",
    "ANALYST_DECISION",
    "INTELLIGENCE_SNAPSHOT",
    "REPORT_GENERATED",
)


class LedgerBlock(Base):
    """One chained block of a case's permissioned integrity ledger."""

    __tablename__ = "ledger_blocks"
    __table_args__ = (UniqueConstraint("case_id", "index", name="uq_ledger_case_index"),)

    id: Mapped[int] = mapped_column(BigSerialId, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    timestamp_iso: Mapped[str] = mapped_column(String(48), nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    block_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    events_json: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LedgerBlock case={self.case_id} #{self.index}>"


class LedgerEvent(Base):
    """A mapped integrity event (chain-of-custody record) for a case."""

    __tablename__ = "ledger_events"

    id: Mapped[int] = mapped_column(BigSerialId, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    block_index: Mapped[int | None] = mapped_column(Integer)
    block_hash: Mapped[str | None] = mapped_column(String(64))
    previous_block_hash: Mapped[str | None] = mapped_column(String(64))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(24), default="REGISTERED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LedgerEvent {self.event_type} {self.transaction_id}>"


class EvidenceIntegrity(Base):
    """Per-source evidence versions with their ledger references."""

    __tablename__ = "evidence_integrity"
    __table_args__ = (UniqueConstraint("case_id", "source_id", "version", name="uq_evidence_version"),)

    id: Mapped[int] = mapped_column(BigSerialId, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)      # file/content digest
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)       # canonical payload hash
    hash_algorithm: Mapped[str] = mapped_column(String(32), default="SHA-256", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="REGISTERED", nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(String(64))
    block_index: Mapped[int | None] = mapped_column(Integer)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EvidenceIntegrity {self.source_id} v{self.version} {self.status}>"


class IntegrityOutbox(Base):
    """Reliable integrity event queue (outbox pattern)."""

    __tablename__ = "integrity_outbox"

    id: Mapped[int] = mapped_column(BigSerialId, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    ledger_transaction_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<IntegrityOutbox {self.event_type} {self.status}>"