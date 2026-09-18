"""Persisted entity + relationship read schemas (Phase 2)."""
from datetime import datetime

from pydantic import BaseModel, Field


class EntityRead(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    confidence: float
    attributes: dict = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class RelationshipRead(BaseModel):
    rel_type: str
    source_id: str
    target_id: str
    confidence: float
    source_ids: list[str] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)
    created_at: datetime


class EntityUpdate(BaseModel):
    """Identity resolution fields for a persisted canonical entity."""

    name: str = Field(min_length=1, max_length=255)
    confidence: float = Field(ge=0, le=1)
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    note: str | None = Field(default=None, max_length=2000)
    location_name: str | None = Field(default=None, max_length=255)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
