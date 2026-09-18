"""Unified intelligence domain models (Phase 1).

Every intelligence engine (fusion, temporal, anomaly, potential-links, gaps,
DNA, priority, info-gain, actions, simulation) consumes one `CaseData` snapshot
and returns these typed, explainable structures. Terminology is analytical
("investigation priority", "potential relationship", "evidence gap") — never a
guilt assertion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Raw case snapshot (single source of truth for all engines)
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """A single observed signal tied to entities/the case."""

    id: str
    source_type: str              # CDR / FIR / TRANSACTION / LOCATION / ...
    source_id: str                # e.g. CDR-001
    timestamp: str = ""
    entity_ids: list[str] = field(default_factory=list)
    summary: str = ""
    reliability: float = 0.5      # 0..1 base reliability of the source type
    record_id: str = ""           # record-level provenance (SOURCE:RECORD)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelData:
    """A persisted relationship with provenance + temporal envelope."""

    source: str
    target: str
    rel_type: str
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    count: int = 1
    timestamps: list[str] = field(default_factory=list)
    amount: float = 0.0
    strength: float = 0.0


@dataclass
class EntityData:
    """A persisted entity with aliases + metadata."""

    id: str
    type: str
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseData:
    """The raw input to the intelligence engine."""

    case_number: str = ""
    entities: list[EntityData] = field(default_factory=list)
    relationships: list[RelData] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    def entity(self, entity_id: str) -> EntityData | None:
        return next((e for e in self.entities if e.id == entity_id), None)

    def neighbors(self, entity_id: str) -> list[str]:
        out: list[str] = []
        for r in self.relationships:
            if r.source == entity_id:
                out.append(r.target)
            elif r.target == entity_id:
                out.append(r.source)
        return out


# ---------------------------------------------------------------------------
# Engine outputs
# ---------------------------------------------------------------------------

@dataclass
class FusionResult:
    """Multi-source evidence fusion for an entity or relationship."""

    subject: str
    score: float                    # 0..100
    level: str                      # HIGH / MEDIUM / LOW
    supporting_evidence: list[str] = field(default_factory=list)
    contradictory_evidence: list[str] = field(default_factory=list)
    factors: list[dict[str, Any]] = field(default_factory=list)
    source_count: int = 0
    independent_source_count: int = 0
    explanation: str = ""


@dataclass
class TemporalChange:
    """An observed network change between two time windows."""

    kind: str                       # NEW_REL / DROPPED_REL / STRENGTHENED / WEAKENED / EMERGING_BRIDGE / BURST
    source: str = ""
    target: str = ""
    window: str = ""
    before: float = 0.0
    after: float = 0.0
    score: float = 0.0
    explanation: str = ""


@dataclass
class Anomaly:
    """An unusual pattern with full explainability (baseline / deviation)."""

    kind: str                       # COMM_BURST / TX_AMOUNT / TX_FREQ / LOCATION / REL_NEW / STRUCTURAL
    entity_id: str = ""
    baseline: float = 0.0
    observed: float = 0.0
    deviation: float = 0.0          # percent change
    score: float = 0.0              # 0..100
    timestamp: str = ""
    evidence: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass
class PotentialLink:
    """A candidate relationship not directly observed (never confirmed)."""

    source: str
    target: str
    score: float                    # 0..100
    supporting_signals: list[str] = field(default_factory=list)
    contradictory_signals: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""


@dataclass
class EvidenceGap:
    """Missing evidence needed to strengthen/reject a hypothesis."""

    subject: str                    # entity or "source<->target"
    known_evidence: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    importance: float = 0.0
    recommended_source: str = "CDR"
    window: str = ""
    explanation: str = ""


@dataclass
class NetworkDNA:
    """A quantitative fingerprint of the network."""

    density: float = 0.0
    centralization: float = 0.0
    community_count: int = 0
    clustering: float = 0.0
    bridge_dependence: str = "LOW"
    bridge_ratio: float = 0.0
    temporal_volatility: float = 0.0
    communication_activity: str = "LOW"
    transaction_anomaly: str = "LOW"
    evidence_coverage: float = 0.0    # percent
    fragmentation: float = 0.0


@dataclass
class PriorityScore:
    """Composite investigative value of an entity/relationship/action."""

    subject: str
    priority: float                 # 0..100
    factors: dict[str, float] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)


@dataclass
class InfoGain:
    """How much new information examining a candidate could reveal."""

    subject: str
    score: float                    # 0..100
    factors: dict[str, float] = field(default_factory=dict)
    expected_value: str = ""
    explanation: str = ""


@dataclass
class Recommendation:
    """A ranked next-best-action."""

    kind: str                       # RELATIONSHIP / ENTITY / TRANSACTION / LOCATION / GAP
    subject: str
    priority: float = 0.0
    info_gain: float = 0.0
    reasoning: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    recommended_data: str = ""
    window: str = ""


@dataclass
class SimulationResult:
    """Outcome of a what-if operation on an isolated graph."""

    operation: str
    subject: str
    before_nodes: int = 0
    after_nodes: int = 0
    before_edges: int = 0
    after_edges: int = 0
    before_communities: int = 0
    after_communities: int = 0
    connectivity_change: float = 0.0
    bridge_before: str = "LOW"
    bridge_after: str = "LOW"
    affected_communities: int = 0
    interpretation: str = ""
    explanation: str = ""