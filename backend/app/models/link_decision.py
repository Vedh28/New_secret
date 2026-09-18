"""Potential-link analyst decision ORM model (P1.3).

Records a human-in-the-loop verdict on a potential (non-observed) relationship:
CONFIRM / REJECT / DEFER. The previous status, new status, analyst, timestamp
and supporting evidence ids are all stored so the decision is traceable and
auditable. A potential link is NEVER auto-promoted to a confirmed relationship
by the engine; only this decision record can change its status.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_types import BigSerialId, JsonType

# Explicit, analyst-facing lifecycle states for a potential relationship.
LINK_STATUSES = ("OBSERVED", "DERIVED", "POTENTIAL", "ANALYST_CONFIRMED", "REJECTED", "DEFERRED")


class PotentialLinkDecision(Base):
    __tablename__ = "potential_link_decisions"
    __table_args__ = (
        UniqueConstraint("case_id", "entity_a", "entity_b", name="uq_decision_pair"),
    )

    id: Mapped[int] = mapped_column(BigSerialId, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    entity_a: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_b: Mapped[str] = mapped_column(String(128), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(24), default="POTENTIAL", nullable=False)
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # CONFIRM | REJECT | DEFER
    analyst_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    evidence_ids: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PotentialLinkDecision {self.entity_a}~{self.entity_b} {self.previous_status}->{self.new_status}>"