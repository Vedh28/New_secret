"""Unified case intelligence service (Phase 14).

Builds the intelligence from a real persisted case (entities, relationships,
evidence), then orchestrates every engine into one structured, cacheable
object. Reuses the existing alerts + case-analytics modules where possible.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Any

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.graph_builder import build_graph
from app.analytics import centrality as cent
from app.analytics import community as comm
from app.intelligence import anomaly, dna, fusion, gaps, info_gain, potential_links, priority, temporal
from app.intelligence.models import CaseData, EntityData, Evidence, PriorityScore, RelData
from app.repositories.case_analytics_repo import build_case_data


class CaseIntelligenceService:
    """One-stop builder for all intelligence results for a case."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(self, case_id: int, cache=None) -> dict[str, Any]:
        """Run the full intelligence pipeline for a case and cache it."""
        if cache is not None and cache.get(case_id):
            return cache[case_id]

        data = await build_case_data(self._session, case_id)

        # --- NetworkX graph for structural metrics ---
        graph = self._to_graph(data)

        # --- Evidence fusion ---
        entity_fusion = {e.id: fusion.fuse_entity(data, e.id) for e in data.entities}
        rel_fusion = {}
        for r in data.relationships:
            key = f"{r.source}<->{r.target}"
            rel_fusion[key] = fusion.fuse_relationship(data, r)

        # --- Temporal + anomalies ---
        boundary = temporal.default_boundary(data) or ""
        temporal_changes = (
            temporal.relationship_trends(data)
            + temporal.network_evolution(data, boundary)
        )
        location_seen: Counter[str] = Counter()
        for r in data.relationships:
            if r.rel_type in ("USES", "VISITED"):
                pass
        for e in data.entities:
            if e.type.upper() == "LOCATION":
                location_seen[e.name or e.id] += 1
        anomalies_full = anomaly.detect_all(data, dict(location_seen) if location_seen else None)
        anomaly_map = {a.entity_id: a.score for a in anomalies_full}

        # --- Potential links + evidence gaps ---
        links = potential_links.discover(data, top_k=12)
        evidence_gaps = gaps.gaps_for_potential_links(data, links)
        evidence_gaps += gaps.gaps_for_low_coverage(data)

        # --- Network DNA ---
        network_dna = dna.compute_dna(graph, data)

        # --- Priority (entities + relationships) ---
        communities = comm.detect_communities(graph)
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

        # --- Analyst decisions on potential links (P1.3) ---
        from app.repositories.link_decision_repository import LinkDecisionRepository
        link_decisions = {
            f"{d.entity_a}<->{d.entity_b}": {
                "decision": d.decision,
                "new_status": d.new_status,
                "previous_status": d.previous_status,
                "analyst_id": d.analyst_id,
                "notes": d.notes,
                "updated_at": d.updated_at.isoformat() if d.updated_at else "",
            }
            for d in await LinkDecisionRepository(self._session).list_by_case(case_id)
        }

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

        if cache is not None:
            cache[case_id] = result
        return result

    def _to_graph(self, data: CaseData) -> nx.Graph:
        graph = nx.Graph()
        for e in data.entities:
            graph.add_node(e.id, type=e.type, name=e.name)
        for r in data.relationships:
            if r.source != r.target:
                graph.add_edge(r.source, r.target, type=r.rel_type,
                               weight=r.strength or r.confidence)
        return graph


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