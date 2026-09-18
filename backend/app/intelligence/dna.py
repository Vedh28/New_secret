"""Network DNA (Phase 8).

A quantitative fingerprint of the network: density, centralization, community
count, clustering, bridge dependence, temporal volatility, activity levels,
evidence coverage and fragmentation. `compare_dna` diffs two snapshots into a
readable before/after summary. All metrics are computed from the graph.
"""
from __future__ import annotations

import networkx as nx

from app.intelligence.models import CaseData, NetworkDNA
from app.analytics.community import detect_communities, connected_components
from app.analytics.centrality import betweenness_centrality, degree_centrality

# Relationship types that count as communication / financial activity.
_COMM_REL = ("CALLED", "MESSAGED")
_TX_REL = ("TRANSFERRED_TO",)


def _bridge_dependence(graph: nx.Graph) -> tuple[str, float]:
    """Ratio of nodes with high betweenness (bridges) over total."""
    if graph.number_of_nodes() == 0:
        return "LOW", 0.0
    betw = betweenness_centrality(graph)
    if not betw:
        return "LOW", 0.0
    mx = max(betw.values()) or 1.0
    high = [n for n, v in betw.items() if mx > 0 and v / mx >= 0.4]
    ratio = len(high) / graph.number_of_nodes()
    level = "HIGH" if ratio >= 0.3 else "MEDIUM" if ratio >= 0.15 else "LOW"
    return level, round(ratio, 3)


def _temporal_volatility(data: CaseData) -> float:
    """Fraction of relationship pairs with a burst count > median (0..1)."""
    counts = [r.count for r in data.relationships]
    if not counts:
        return 0.0
    median = sorted(counts)[len(counts) // 2] or 1
    volatile = sum(1 for c in counts if c >= 2 * median and median > 0)
    return round(volatile / len(counts), 3)


def _activity_level(counts: list[float], threshold: float) -> str:
    if not counts:
        return "LOW"
    avg = sum(counts) / len(counts)
    if avg >= threshold:
        return "HIGH"
    if avg >= threshold * 0.4:
        return "MEDIUM"
    return "LOW"


def compute_evidence_coverage(data: CaseData) -> float:
    """Evidence coverage for a case snapshot (0..100%).

    An entity is fully covered (1.0) when at least one persisted evidence
    record references it; it is weakly covered (0.5) when it only carries a
    source reference in its own provenance; uncovered is 0. The score is the
    mean across all case entities — never an artifact of graph size (`n/n`).
    0% when every entity is unverified.
    """
    total = len(data.entities)
    if total == 0:
        return 0.0
    referenced: set[str] = set()
    for e in data.evidence:
        referenced.update(e.entity_ids)

    score = 0.0
    for ent in data.entities:
        if ent.id in referenced:
            score += 1.0
        elif ent.source_ids:
            score += 0.5
    return round(score * 100.0 / total, 1)


def compute_dna(graph: nx.Graph, data: CaseData | None = None) -> NetworkDNA:
    """Compute a DNA fingerprint from a NetworkX graph (+ optional raw case data)."""
    n = graph.number_of_nodes()
    density = float(nx.density(graph))
    components = connected_components(graph)
    comms = detect_communities(graph)
    try:
        clustering = float(nx.average_clustering(graph))
    except Exception:  # noqa: BLE001 - small/empty graphs
        clustering = 0.0

    degree = degree_centrality(graph)
    centrality_vals = list(degree.values())
    centralization = (sum(centrality_vals) / n) if n else 0.0

    bridge_level, bridge_ratio = _bridge_dependence(graph)

    comm_activity, tx_activity = ("LOW", "LOW")
    temporal_volatility = 0.0
    evidence_coverage = 0.0
    tx_anomaly = "LOW"
    if data is not None:
        comm_counts = [r.count for r in data.relationships if r.rel_type in _COMM_REL]
        tx_counts = [r.amount for r in data.relationships if r.rel_type in _TX_REL if r.amount > 0]
        comm_activity = _activity_level(comm_counts, 2.0)
        tx_activity = _activity_level(tx_counts, 1_000_000.0)
        temporal_volatility = _temporal_volatility(data)
        med_tx = sorted(tx_counts)[len(tx_counts) // 2] if tx_counts else 0
        if med_tx and any(a >= 3 * med_tx for a in tx_counts):
            tx_anomaly = "HIGH"
        elif tx_counts:
            tx_anomaly = "MEDIUM"
        evidence_coverage = compute_evidence_coverage(data)

    fragmentation = 1.0 - (1.0 / len(components)) if components else 0.0

    return NetworkDNA(
        density=round(density, 3),
        centralization=round(centralization, 3),
        community_count=len(comms),
        clustering=round(clustering, 3),
        bridge_dependence=bridge_level,
        bridge_ratio=bridge_ratio,
        temporal_volatility=temporal_volatility,
        communication_activity=comm_activity,
        transaction_anomaly=tx_anomaly,
        evidence_coverage=round(evidence_coverage, 1),
        fragmentation=round(fragmentation, 3),
    )


def compare_dna(before: NetworkDNA, after: NetworkDNA) -> dict:
    """Describe how the network changed between two DNA snapshots."""
    return {
        "density": round(after.density - before.density, 3),
        "centralization": round(after.centralization - before.centralization, 3),
        "community_count": after.community_count - before.community_count,
        "clustering": round(after.clustering - before.clustering, 3),
        "bridge_dependence": f"{before.bridge_dependence} -> {after.bridge_dependence}" if
        before.bridge_dependence != after.bridge_dependence else after.bridge_dependence,
        "temporal_volatility": round(after.temporal_volatility - before.temporal_volatility, 3),
        "evidence_coverage": round(after.evidence_coverage - before.evidence_coverage, 1),
        "fragmentation": round(after.fragmentation - before.fragmentation, 3),
    }