"""Optional EVM adapter (Phase 24) — configuration-driven stub.

The SIH deployment uses `LocalPermissionedLedger`. This adapter documents the
same contract for a future permissioned EVM chain without adding fragile
dependencies (wallets, gas, tokens). It is intentionally non-functional so a
wrong `BLOCKCHAIN_PROVIDER=evm` fails loudly instead of pretending to work.
"""
from __future__ import annotations

from app.blockchain.interface import BlockchainLedger


class EvmUnavailableError(RuntimeError):
    pass


class EvmBlockchainAdapter(BlockchainLedger):
    """Contract-compatible stub: raises until a real EVM deployment is wired."""

    def genesis_params(self, case_id: str) -> dict:
        return {"case_id": str(case_id), "chain": "evm-permissioned", "genesis_previous": "0" * 64}

    def compute_block(self, *, previous, case_id: str, events: list[dict]):
        raise EvmUnavailableError(
            "BLOCKCHAIN_PROVIDER=evm is not implemented in this prototype; use provider=local."
        )

    def verify_chain(self, blocks, genesis_params):
        raise EvmUnavailableError("EVM chain verification is not implemented in this prototype.")