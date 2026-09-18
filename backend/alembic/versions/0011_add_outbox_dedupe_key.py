"""add atomic snapshot/outbox dedupe key (Phase 1/2).

Revision ID: 0011_add_outbox_dedupe_key
Revises: 0010_add_reports
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0011_add_outbox_dedupe_key"
down_revision: str | None = "0010_add_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE integrity_outbox ADD COLUMN dedupe_key VARCHAR(512);"
    )
    # Unique index allows multiple NULLs (Postgres + SQLite), so non-idempotent
    # events remain unrestricted while idempotent identities are atomic.
    op.execute(
        "CREATE UNIQUE INDEX uq_outbox_dedupe_key ON integrity_outbox (dedupe_key);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_outbox_dedupe_key;")
    op.execute("ALTER TABLE integrity_outbox DROP COLUMN dedupe_key;")