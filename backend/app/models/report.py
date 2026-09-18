"""Persisted report ORM model (P0.2).

Reports now survive application restarts: PostgreSQL is the authoritative
report store, the PDF artifact + sections are persisted, and `report_hash` is
the canonical cryptographic commitment that the integrity ledger references.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_types import JsonType


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    sections_json: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    artifact: Mapped[str] = mapped_column(String, default="", nullable=False)      # base64 PDF preview
    artifact_mime: Mapped[str] = mapped_column(String(64), default="application/pdf", nullable=False)
    report_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Report {self.id} {self.report_type!r} case={self.case_id}>"