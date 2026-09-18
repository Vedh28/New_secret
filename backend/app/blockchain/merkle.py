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


def _tree_levels(leaf_hashes: list[str]) -> list[list[str]]:
    """Deterministic level-by-level tree (sorted leaves, self-pair odd node).

    Returns `[leaves, parents, ..., root]`. Empty leaves -> [].
    """
    level = sorted(leaf for leaf in (leaf_hashes or []) if leaf)
    levels: list[list[str]] = []
    while level:
        levels.append(level)
        if len(level) == 1:
            break
        if len(level) % 2 == 1:
            level = level + [level[-1]]  # pair the last node with itself
        level = [
            hash_bytes(left.encode("utf-8") + right.encode("utf-8"))
            for left, right in zip(level[0::2], level[1::2])
        ]
    return levels


def build_merkle_proof(leaf_hash: str, leaf_hashes: list[str]) -> dict | None:
    """Merkle inclusion proof for `leaf_hash` within the batch.

    Returns {leaf, root, siblings:[{hash, side}]} or None when the leaf is not
    part of the batch. The proof reconstructs the stored root bottom-up.
    `side` is "right"/"left" relative to the proof leaf at each level; an odd
    leaf level self-pairs its final node ("self").
    """
    levels = _tree_levels(leaf_hashes)
    if not levels:
        return None
    leaves = levels[0]
    if leaf_hash not in leaves:
        return None

    current_index = leaves.index(leaf_hash)
    siblings: list[dict] = []
    for level in levels[:-1]:
        node_count = len(level)
        if current_index % 2 == 0 and (current_index + 1) >= node_count:
            sibling = level[current_index]
            side = "self"
        else:
            pair = current_index ^ 1
            sibling = level[pair]
            side = "right" if current_index % 2 == 0 else "left"
        siblings.append({"hash": sibling, "side": side})
        current_index = current_index // 2

    return {"leaf": leaf_hash, "root": levels[-1][0], "siblings": siblings}


def verify_merkle_proof(proof: dict, root: str) -> bool:
    """Reconstruct the root from a proof and compare it with `root`."""
    if not proof:
        return False
    current = proof.get("leaf")
    for sibling in proof.get("siblings", []):
        if not current or not sibling.get("hash"):
            return False
        if sibling.get("side") == "self":
            current = hash_bytes(current.encode("utf-8") + current.encode("utf-8"))
            continue
        left, right = (sibling["hash"], current) if sibling.get("side") == "left" else (current, sibling["hash"])
        current = hash_bytes(left.encode("utf-8") + right.encode("utf-8"))
    return bool(current) and current == root