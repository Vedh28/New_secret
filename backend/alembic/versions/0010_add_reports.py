"""add reports persistence table (P0.2).

Revision ID: 0010_add_reports
Revises: 0009_add_integrity_ledger
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0010_add_reports"
down_revision: str | None = "0009_add_integrity_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE reports (
            id VARCHAR(64) PRIMARY KEY,
            case_id BIGINT REFERENCES cases(id) ON DELETE CASCADE,
            report_type VARCHAR(40) NOT NULL,
            title VARCHAR(255) NOT NULL,
            generated_by VARCHAR(128) NOT NULL,
            sections_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            artifact TEXT NOT NULL DEFAULT '',
            artifact_mime VARCHAR(64) NOT NULL DEFAULT 'application/pdf',
            report_hash VARCHAR(64) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_reports_case ON reports (case_id);
        CREATE INDEX idx_reports_generated ON reports (generated_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reports;")