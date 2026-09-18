"""Unified case intelligence service (Phase 14, hardened).

CASE INTELLIGENCE SERVICE is the single intelligence aggregation layer.

    SELECTED CASE
        -> build_case_data (persisted entities/relationships/evidence)
        -> decisions (analyst status per potential link)
        -> compute_from_data(...)
        -> ONE canonical intelligence snapshot
        -> Assistant / Network UI / Reports / Dashboard

`build(case_id)` loads persistence + analyst decisions and computes the
snapshot. `compute_from_data(...)` is a pure, cacheable computation so offline
clients and tests derive the SAME structure from the SAME contract.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import centrality as cent
from app.analytics import community as comm
from app.intelligence import anomaly, dna, fusion, gaps, info_gain, locations, potential_links, priority, temporal
from app.intelligence.models import CaseData, PriorityScore
from app.repositories.case_analytics_repo import build_case_data


class CaseIntelligenceService:
    """One-stop builder for all intelligence results for a case."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(self, case_id: int, cache=None, register_integrity: bool = True,
                    actor_id: int | None = None) -> dict[str, Any]:
        """Load persisted case data + analyst decisions and compute the snapshot.

        When `register_integrity` is true and the snapshot is freshly computed,
        an INTEGRITY SNAPSHOT event is enqueued (outbox) — never blocking the
        intelligence pipeline and never recomputing it.
        """
        if cache is not None and cache.get(case_id):
            return cache[case_id]

        data = await build_case_data(self._session, case_id)
        decisions = await self._load_decisions(case_id)
        result = compute_from_data(case_id, data, decisions)

        if register_integrity:
            await self._register_snapshot_integrity(case_id, result, actor_id)

        if cache is not None:
            cache[case_id] = result
        return result

    async def _register_snapshot_integrity(self, case_id: int, result: dict,
                                           actor_id: int | None) -> None:
        """Idempotent intelligence snapshot registration (best-effort).

        The fingerprint identity is (case_id + snapshot_hash + engine_version),
        so rebuilding the same analytical state does NOT create duplicate
        ledger events. Blockchain availability must never affect investigation
        analytics, so failures are swallowed after leaving a retryable signal.
        """
        try:
            from app.blockchain.service import BlockchainIntegrityService
            await BlockchainIntegrityService(self._session).enqueue_snapshot(
                case_id=case_id,
                snapshot_hash=_snapshot_fingerprint(result),
                engine_version="1.x",
                actor_id=actor_id,
            )
        except Exception:  # noqa: BLE001 - integrity layer must never block analytics
            pass

    async def _load_decisions(self, case_id: int) -> dict[str, dict]:
        """Analyst decisions keyed by canonical '<->' sorted pair."""
        from app.repositories.link_decision_repository import LinkDecisionRepository

        return {
            _pair_key(d.entity_a, d.entity_b): {
                "decision": d.decision,
                "new_status": d.new_status,
                "previous_status": d.previous_status,
                "analyst_id": d.analyst_id,
                "notes": d.notes,
                "updated_at": d.updated_at.isoformat() if d.updated_at else "",
            }
            for d in await LinkDecisionRepository(self._session).list_by_case(case_id)
        }

    def _to_graph(self, data: CaseData) -> nx.Graph:
        graph = nx.Graph()
        for e in data.entities:
            graph.add_node(e.id, type=e.type, name=e.name)
        for r in data.relationships:
            if r.source != r.target:
                graph.add_edge(r.source, r.target, type=r.rel_type,
                               weight=r.strength or r.confidence)
        return graph


def compute_from_data(case_id: int, data: CaseData, link_decisions: dict[str, dict] | None = None) -> dict[str, Any]:
    """Compute the canonical case intelligence snapshot from a CaseData.

    Pure computation: same input -> same output. Used by the live service,
    offline demo snapshots and tests so every consumer shares one algorithm.
    """
    link_decisions = link_decisions or {}

    # --- NetworkX graph for structural metrics ---
    graph = _to_graph(data)

    # --- Community structure (single source, reused everywhere) ---
    communities = comm.detect_communities(graph)

    # --- Evidence fusion ---
    entity_fusion = {e.id: fusion.fuse_entity(data, e.id) for e in data.entities}
    rel_fusion = {}
    for r in data.relationships:
        key = f"{r.source}<->{r.target}"
        rel_fusion[key] = fusion.fuse_relationship(data, r)

    # --- Temporal + anomalies (both strictly case-scoped) ---
    boundary = temporal.default_boundary(data) or ""
    temporal_changes = (
        temporal.relationship_trends(data)
        + temporal.network_evolution(data, boundary)
        + temporal.emerging_bridges(data, communities, boundary)
    )
    case_locations = locations.case_location_observations(data)
    anomalies_full = anomaly.detect_all(data, case_locations or None)
    anomaly_map = {a.entity_id: a.score for a in anomalies_full}

    # --- Potential links + evidence gaps ---
    links = potential_links.discover(data, top_k=12)
    evidence_gaps = gaps.gaps_for_potential_links(data, links)
    evidence_gaps += gaps.gaps_for_low_coverage(data)

    # --- Network DNA ---
    network_dna = dna.compute_dna(graph, data)

    # --- Priority (entities + relationships) ---
    degree = cent.degree_centrality(graph)
    betweenness = cent.betweenness_centrality(graph)
    source_counts: dict[str, int] = {}
    for r in data.relationships:
        for eid in (r.source, r.target):
            source_counts[eid] = source_counts.get(eid, 0) + len(r.source_ids)
    evidence_scores = {e.id: fusion.fuse_entity(data, e.id).score for e in data.entities}
    entity_priorities = priority.rank_entities(
        data, degree, betweenness, communities, anomaly_map,
        evidence_scores, source_counts,
    )
    entity_priority_map = {p.subject: p for p in entity_priorities}

    link_priorities: list[PriorityScore] = []
    for link in links:
        link_priorities.append(priority.score_relationship(
            subject=f"{link.source}<->{link.target}",
            strength=link.score,
            anomaly_score=anomaly_map.get(link.source, 0.0),
            evidence_score=min(100.0, len(link.supporting_signals) * 20.0),
            cross_community=1 if link.supporting_signals else 0,
            source_count=0,
        ))
    link_infos = {
        f"{l.source}<->{l.target}": info_gain.potential_link_gain(data, l) for l in links
    }

    # --- Information gain ---
    entity_gains = {}
    for p in entity_priorities[:12]:
        entity_gains[p.subject] = info_gain.entity_gain(
            data, p.subject,
            uncertainty=100.0 - min(100.0, source_counts.get(p.subject, 0) * 20.0),
            affected=len(data.neighbors(p.subject)),
        )
    gap_infos = [info_gain.gap_gain(g) for g in evidence_gaps]

    # --- Next best actions ---
    recommendations = _build_recommendations(data, entity_priorities, entity_gains,
                                             links, link_priorities, link_infos, evidence_gaps)

    result = {
        "case_id": case_id,
        "entities": data.entities,
        "relationships": data.relationships,
        "evidence": data.evidence,
        "evidence_fusion": {k: _d(v) for k, v in entity_fusion.items()},
        "relationship_fusion": {k: _d(v) for k, v in rel_fusion.items()},
        "temporal_changes": [_d(c) for c in temporal_changes],
        "anomalies": [_d(a) for a in anomalies_full],
        "potential_links": [_d(p) for p in links],
        "link_decisions": link_decisions,
        "evidence_gaps": [_d(g) for g in evidence_gaps],
        "network_dna": _d(network_dna),
        "entity_priorities": [_d(p) for p in entity_priorities],
        "relationship_priorities": [_d(p) for p in link_priorities],
        "information_gain": {k: _d(v) for k, v in entity_gains.items()}
                          | {k: _d(v) for k, v in link_infos.items()},
        "recommendations": [_d(r) for r in recommendations],
    }
    return result


def _to_graph(data: CaseData) -> nx.Graph:
    graph = nx.Graph()
    for e in data.entities:
        graph.add_node(e.id, type=e.type, name=e.name)
    for r in data.relationships:
        if r.source != r.target:
            graph.add_edge(r.source, r.target, type=r.rel_type,
                           weight=r.strength or r.confidence)
    return graph


def _pair_key(a: str, b: str) -> str:
    return "<->".join(sorted([a, b]))


def _build_recommendations(data, entity_priorities, entity_gains, links, link_priorities,
                           link_infos, evidence_gaps) -> list:
    """Wrap next-best-action engine around counted inputs."""
    from app.intelligence.actions import build

    return build(
        data=data,
        entity_priorities=entity_priorities,
        entity_gains=entity_gains,
        potential_links=links,
        link_priorities=link_priorities,
        link_gains=link_infos,
        gaps=evidence_gaps,
    )


def _d(dataclass_obj) -> dict:
    return asdict(dataclass_obj)


def _snapshot_fingerprint(result: dict) -> str:
    """Deterministic metrics-only fingerprint for a canonical snapshot."""
    from app.blockchain.hashes import hash_intelligence_snapshot
    return hash_intelligence_snapshot(result)