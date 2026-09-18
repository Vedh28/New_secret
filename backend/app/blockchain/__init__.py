"""Evidence integrity & provenance layer (blockchain abstraction).

PostgreSQL stays authoritative; Neo4j stays the derived graph; NetworkX stays
analytics. This package adds the tamper-evident integrity ledger:

    hashing      -> deterministic canonical SHA-256
    merkle       -> batched record integrity roots
    local_ledger -> chained permissioned blocks (per case)
    service      -> outbox + registration + verification orchestration
"""
from app.blockchain.service import BlockchainIntegrityService  # noqa: F401