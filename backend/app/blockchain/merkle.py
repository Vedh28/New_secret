"""Deterministic Merkle root utility (integrity layer).

Batches of record hashes are aggregated into ONE ledger identifier:

    leaves (sorted ascending lexicographically)  - deterministic
    odd count  - the final node is paired with itself
    parent     - SHA256(left || right) hex-upper

Empty input has no root (returns None). The rule is documented and fixed so a
record can be re-verified against its batch at any time.
"""
from __future__ import annotations

from app.blockchain.hashes import hash_bytes


def merkle_root(leaf_hashes: list[str]) -> str | None:
    """Return the deterministic Merkle root over `leaf_hashes`, or None."""
    level = sorted(leaf for leaf in (leaf_hashes or []) if leaf)
    if not level:
        return None
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # pair the last node with itself
        level = [
            hash_bytes(left.encode("utf-8") + right.encode("utf-8"))
            for left, right in zip(level[0::2], level[1::2])
        ]
    return level[0]


def batch_integrity(record_hashes: list[str]) -> dict:
    """One-shot aggregation helper used during ingestion batching."""
    return {
        "algorithm": "MERKLE-SHA256",
        "record_count": len(record_hashes or []),
        "merkle_root": merkle_root(record_hashes),
    }