"""SQLAlchemy ORM models.

Importing each model registers it on Base.metadata (used by Alembic autogenerate
and by `create_all` helpers).
"""
from app.models.user import User, UserRole, UserStatus
from app.models.criminal import CriminalProfile, EntityType, RiskLevel
from app.models.case import Case, CaseCriminal, CasePriority, CaseStatus
from app.models.audit import AuditLog
from app.models.alert import Alert
from app.models.entity import Entity, EntityRelationship
from app.models.lead import Lead
from app.models.source import Source
from app.models.link_decision import PotentialLinkDecision
from app.models.integrity import (
    EvidenceIntegrity,
    IntegrityFlushLock,
    IntegrityOutbox,
    LedgerBlock,
    LedgerEvent,
)
from app.models.report import Report

__all__ = [
    "User",
    "UserRole",
    "UserStatus",
    "CriminalProfile",
    "EntityType",
    "RiskLevel",
    "Case",
    "CaseCriminal",
    "CasePriority",
    "CaseStatus",
    "AuditLog",
    "Alert",
    "Entity",
    "EntityRelationship",
    "Lead",
    "Source",
    "PotentialLinkDecision",
    "LedgerBlock",
    "LedgerEvent",
    "EvidenceIntegrity",
    "IntegrityOutbox",
    "IntegrityFlushLock",
    "Report",
]
