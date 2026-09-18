"""Potential-link decision schemas (P1.3)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.intelligence.status import VALID_DECISIONS

_DECISION_PATTERN = "^(" + "|".join(VALID_DECISIONS) + ")$"


class LinkDecisionCreate(BaseModel):
    """Analyst verdict on a potential relationship."""

    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    decision: str = Field(pattern=_DECISION_PATTERN)
    evidence_ids: list[str] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=1000)


class LinkDecisionRead(BaseModel):
    id: int
    case_id: int
    entity_a: str
    entity_b: str
    previous_status: str
    new_status: str
    decision: str
    analyst_id: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime
    updated_at: datetime