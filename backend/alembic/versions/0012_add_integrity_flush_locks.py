"""add integrity_flush_locks (case-scoped flush serialization, Phase 3).

Revision ID: 0012_add_integrity_flush_locks
Revises: 0011_add_outbox_dedupe_key
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0012_add_integrity_flush_locks"
down_revision: str | None = "0011_add_outbox_dedupe_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The SQLite-functional fallback lock table. PostgreSQL serializes flushes
    # with transaction-scoped advisory locks and never needs this row.
    op.execute(
        """
        CREATE TABLE integrity_flush_locks (
            case_id VARCHAR(128) PRIMARY KEY,
            holder VARCHAR(32),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS integrity_flush_locks;")