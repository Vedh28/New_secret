"""add evidence quality ledger tables (integrity layer).

Revision ID: 0009_add_integrity_ledger
Revises: 0008_canonical_hypothesis_statuses
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0009_add_integrity_ledger"
down_revision: str | None = "0008_canonical_hypothesis_statuses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ledger_blocks (
            id BIGSERIAL PRIMARY KEY,
            case_id VARCHAR(128) NOT NULL,
            index INTEGER NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
            timestamp_iso VARCHAR(48) NOT NULL,
            previous_hash VARCHAR(64) NOT NULL,
            data_hash VARCHAR(64) NOT NULL,
            block_hash VARCHAR(64) NOT NULL,
            events_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ledger_case_index UNIQUE (case_id, index)
        );
        CREATE INDEX idx_ledger_blocks_case ON ledger_blocks (case_id);

        CREATE TABLE ledger_events (
            id BIGSERIAL PRIMARY KEY,
            transaction_id VARCHAR(64) NOT NULL UNIQUE,
            case_id VARCHAR(128) NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            entity_type VARCHAR(40),
            entity_id VARCHAR(128),
            payload_hash VARCHAR(64),
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            block_index INTEGER,
            block_hash VARCHAR(64),
            previous_block_hash VARCHAR(64),
            actor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'REGISTERED',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX idx_ledger_events_case ON ledger_events (case_id);
        CREATE INDEX idx_ledger_events_case_type ON ledger_events (case_id, event_type);

        CREATE TABLE evidence_integrity (
            id BIGSERIAL PRIMARY KEY,
            case_id VARCHAR(128) NOT NULL,
            source_id VARCHAR(64) NOT NULL,
            evidence_hash VARCHAR(64) NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            hash_algorithm VARCHAR(32) NOT NULL DEFAULT 'SHA-256',
            version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(24) NOT NULL DEFAULT 'REGISTERED',
            transaction_id VARCHAR(64),
            block_index INTEGER,
            actor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_evidence_version UNIQUE (case_id, source_id, version)
        );
        CREATE INDEX idx_evidence_integrity_case ON evidence_integrity (case_id);
        CREATE INDEX idx_evidence_integrity_source ON evidence_integrity (case_id, source_id);

        CREATE TABLE integrity_outbox (
            id BIGSERIAL PRIMARY KEY,
            case_id VARCHAR(128) NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            entity_type VARCHAR(40),
            entity_id VARCHAR(128),
            payload_hash VARCHAR(64) NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            actor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            ledger_transaction_id VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            processed_at TIMESTAMPTZ
        );
        CREATE INDEX idx_integrity_outbox_case ON integrity_outbox (case_id);
        CREATE INDEX idx_integrity_outbox_status ON integrity_outbox (status);
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS integrity_outbox; "
        "DROP TABLE IF EXISTS evidence_integrity; "
        "DROP TABLE IF EXISTS ledger_events; "
        "DROP TABLE IF EXISTS ledger_blocks;"
    )