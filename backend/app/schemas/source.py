"""Source schemas (Phase 2-3)."""
from datetime import datetime

from pydantic import BaseModel, Field


class SourceCreate(BaseModel):
    """Register a case data source."""

    source_id: str = Field(min_length=1, max_length=64)
    filename: str = Field(min_length=1, max_length=255)
    file_type: str | None = None
    source_type: str | None = Field(default=None, max_length=32)
    record_count: int | None = None
    payload: dict = Field(default_factory=dict)


class SourceRead(BaseModel):
    id: int
    source_id: str
    filename: str
    file_type: str | None = None
    source_type: str | None = None
    status: str
    record_count: int | None = None
    processing_error: str | None = None
    metadata_json: dict = Field(default_factory=dict)
    uploaded_at: datetime
    processed_at: datetime | None = None


class SourceProcessResult(BaseModel):
    source_id: str
    filename: str
    case_id: int
    status: str
    record_count: int
    metrics: dict = Field(default_factory=dict)


class SourceUploadResult(BaseModel):
    source_id: str
    filename: str
    case_id: int
    format: str
    status: str
    record_count: int
    quality: dict = Field(default_factory=dict)
    error: str | None = None
    evidence_hash: str | None = None          # SHA-256 of uploaded bytes
    integrity_status: str | None = None       # REGISTERED / PENDING / LEDGER_UNAVAILABLE
