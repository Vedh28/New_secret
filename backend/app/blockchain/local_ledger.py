"""Permissioned local ledger engine (Phases 1-2).

A REAL chained block structure — genesis → block → block — with SHA-256 block
hashing that depends on index, timestamp, previous_hash and an aggregate event
data hash. No proof-of-work (permissioned integrity ledger, not a
cryptocurrency). Pure/deterministic so it is unit-testable and re-verifiable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.blockchain.hashes import hash_json, hash_text
from app.blockchain.interface import Block, BlockchainLedger, ChainVerification

GENESIS_PREVIOUS_HASH = "0" * 64
CHAIN_VERSION = "secret-ledger-v1"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _data_hash(events: list[dict]) -> str:
    """Deterministic aggregate hash over the block's event payload hashes."""
    event_hashes = [e.get("hash") or hash_json(e) for e in events]
    return hash_json({"chain": CHAIN_VERSION, "event_hashes": sorted(event_hashes)})


class LocalPermissionedLedger(BlockchainLedger):
    """Deterministic permissioned chain engine (per-case chains)."""

    def genesis_params(self, case_id: str) -> dict:
        return {"case_id": str(case_id), "chain": CHAIN_VERSION, "genesis_previous": GENESIS_PREVIOUS_HASH}

    def compute_block(self, *, previous: Block | None, case_id: str,
                      events: list[dict]) -> Block:
        index = 0 if previous is None else previous.index + 1
        timestamp = _utcnow()
        prev_hash = previous.hash if previous is not None else GENESIS_PREVIOUS_HASH
        data_hash = _data_hash(events)
        # Block hash depends on index + timestamp + previous hash + data hash.
        block_hash = hash_json({
            "chain": CHAIN_VERSION,
            "case_id": str(case_id),
            "index": index,
            "timestamp": timestamp,
            "previous_hash": prev_hash,
            "data_hash": data_hash,
        })
        return Block(
            index=index,
            timestamp=timestamp,
            previous_hash=prev_hash,
            data_hash=data_hash,
            hash=block_hash,
            case_id=str(case_id),
            events=[_event_ref(e) for e in events],
        )

    def verify_chain(self, blocks: list[Block], genesis_params: dict) -> ChainVerification:
        issues: list[str] = []

        if not blocks:
            return ChainVerification(chain_valid=False, blocks=0,
                                     issues=["chain is empty"], genesis_valid=False)

        first = blocks[0]
        expected_genesis_previous = genesis_params.get("genesis_previous", GENESIS_PREVIOUS_HASH)
        genesis_valid = first.index == 0 and first.previous_hash == expected_genesis_previous
        if not genesis_valid:
            issues.append("genesis block is invalid (index or previous_hash)")

        previous_hashes_valid = True
        block_hashes_valid = True
        for position, block in enumerate(blocks):
            # Recompute the block hash and compare.
            expect_hash = hash_json({
                "chain": CHAIN_VERSION,
                "case_id": str(block.case_id),
                "index": block.index,
                "timestamp": block.timestamp,
                "previous_hash": block.previous_hash,
                "data_hash": block.data_hash,
            })
            if block.hash != expect_hash:
                block_hashes_valid = False
                issues.append(f"block #{block.index} hash mismatch")
            if position > 0:
                if block.previous_hash != blocks[position - 1].hash:
                    previous_hashes_valid = False
                    issues.append(f"block #{block.index} breaks previous-hash chaining")
            if block.index != position:
                issues.append(f"block #{block.index} index sequence broken")

        return ChainVerification(
            chain_valid=genesis_valid and previous_hashes_valid and block_hashes_valid and not issues,
            blocks=len(blocks),
            issues=issues,
            previous_hashes_valid=previous_hashes_valid,
            block_hashes_valid=block_hashes_valid,
            genesis_valid=genesis_valid,
        )


def _event_ref(event: dict) -> dict:
    """One-line non-sensitive event reference stored in the block."""
    return {
        "transaction_id": event.get("transaction_id", ""),
        "event_type": event.get("event_type", ""),
        "entity_type": event.get("entity_type", ""),
        "entity_id": event.get("entity_id", ""),
        "payload_hash": event.get("payload_hash", ""),
        "hash": event.get("hash") or hash_json(event),
    }