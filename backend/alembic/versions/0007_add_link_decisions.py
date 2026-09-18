"""add potential_link_decisions table (P1.3).

Revision ID: 0007_add_link_decisions
Revises: 0006_add_investigative_leads
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0007_add_link_decisions"
down_revision: str | None = "0006_add_investigative_leads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE potential_link_decisions (
            id BIGSERIAL PRIMARY KEY,
            case_id BIGINT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            entity_a VARCHAR(128) NOT NULL,
            entity_b VARCHAR(128) NOT NULL,
            previous_status VARCHAR(24) NOT NULL DEFAULT 'POTENTIAL',
            new_status VARCHAR(24) NOT NULL,
            decision VARCHAR(16) NOT NULL,
            analyst_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_decision_pair UNIQUE (case_id, entity_a, entity_b)
        );
        CREATE INDEX idx_link_decisions_case ON potential_link_decisions (case_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS potential_link_decisions;")