"""canonicalize hypothesis statuses (P1-5).

Maps legacy investigative-lead statuses onto the canonical vocabulary shared
with potential-link decisions:
    NEW -> POTENTIAL, CONFIRMED -> ANALYST_CONFIRMED, DISMISSED -> REJECTED

Revision ID: 0008_canonical_hypothesis_statuses
Revises: 0007_add_link_decisions
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0008_canonical_hypothesis_statuses"
down_revision: str | None = "0007_add_link_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE investigative_leads SET status = 'POTENTIAL' WHERE status = 'NEW';"
    )
    op.execute(
        "UPDATE investigative_leads SET status = 'ANALYST_CONFIRMED' WHERE status = 'CONFIRMED';"
    )
    op.execute(
        "UPDATE investigative_leads SET status = 'REJECTED' WHERE status = 'DISMISSED';"
    )


def downgrade() -> None:
    # Reversible one-way vocabulary map (best-effort inverse).
    op.execute(
        "UPDATE investigative_leads SET status = 'NEW' WHERE status = 'POTENTIAL';"
    )
    op.execute(
        "UPDATE investigative_leads SET status = 'CONFIRMED' WHERE status = 'ANALYST_CONFIRMED';"
    )
    op.execute(
        "UPDATE investigative_leads SET status = 'DISMISSED' WHERE status = 'REJECTED';"
    )