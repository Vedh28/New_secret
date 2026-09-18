"""Canonical analyst/hypothesis status model (P1-5).

Single vocabulary shared by potential-link decisions AND investigative leads,
so the same decision displays identically everywhere. A hypothesis is never
auto-promoted: only an explicit analyst action moves it through these states.

Relationship lifecycle:      OBSERVED -> DERIVED -> POTENTIAL -> (analyst) -> ...
Terminal analyst decisions:  ANALYST_CONFIRMED | REJECTED | DEFERRED
Reviewing bucket (managed):  REVIEWING
"""
from __future__ import annotations

# Full canonical lifecycle vocabulary.
LINK_STATUSES = (
    "OBSERVED",
    "DERIVED",
    "POTENTIAL",
    "REVIEWING",
    "ANALYST_CONFIRMED",
    "REJECTED",
    "DEFERRED",
)

# Statuses a fresh hypothesis starts as.
HYPOTHESIS_OPEN = ("POTENTIAL", "REVIEWING")

# Analyst actions (decision verbs) and the status they produce.
ANALYST_DECISION_TO_STATUS = {
    "CONFIRM": "ANALYST_CONFIRMED",
    "REJECT": "REJECTED",
    "DEFER": "DEFERRED",
}
VALID_DECISIONS = tuple(ANALYST_DECISION_TO_STATUS)

# Transition targets offered to an analyst for a hypothesis in flight.
ANALYST_ACTIONS = ("CONFIRM", "REJECT", "DEFER")

# Legacy vocabulary -> canonical (used by forward migrations).
LEGACY_LEAD_STATUS_MAP = {
    "NEW": "POTENTIAL",
    "CONFIRMED": "ANALYST_CONFIRMED",
    "DISMISSED": "REJECTED",
}


def canonical_lead_status(status: str) -> str:
    """Map a legacy lead status onto the canonical vocabulary."""
    return LEGACY_LEAD_STATUS_MAP.get(status, status)