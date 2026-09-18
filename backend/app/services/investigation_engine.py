"""Investigation engine (original Phase 10).

Orchestrates the full investigation workflow end-to-end:
  generate synthetic records -> ingest (adapters) -> extract entities/relationships
  -> resolve duplicates -> build knowledge graph -> run analytics -> summarize.
Operates on the injected graph store (in-memory for tests, Neo4j in prod).
"""
from __future__ import annotations

from app.analysis import location as loc
from app.analysis import temporal as tm
from app.ingestion.adapters import normalize_record
from app.ingestion.generator import generate_synthetic
from app.ingestion.providers import get_extraction_provider
from app.ingestion.resolution import resolve
from app.graph.types import GraphEdge, GraphNode
from app.analytics.graph_builder import build_graph
from app.analytics import community, kingpin, risk


class InvestigationEngine:
    """Run a full investigation pipeline over a synthetic scenario."""

    def __init__(self, store) -> None:
        self._store = store

    async def run(self, scenario: str = "NORMAL_NETWORK", seed: int = 42) -> dict:
        """Execute the workflow and return a structured summary."""
        # 1. Generate synthetic source records.
        raw_records = generate_synthetic(scenario, seed=seed)

        # 2. Ingest / normalize via adapters.
        records = [
            normalize_record(r.source_type, {"id": r.record_id, "timestamp": r.timestamp, "text": r.text, **r.fields})
            for r in raw_records
        ]

        # 3. Extract entities + relationships.
        extraction = get_extraction_provider().extract(records)

        # 4. Entity resolution over extracted mentions (known aliases from scenario records).
        known: dict[str, list[str]] = {}
        for e in extraction.entities:
            known.setdefault(e.entity_id, []).append(e.name)
        resolution_candidates = resolve(known, extraction.entities)
        resolved_ids = extract_entity_ids(extraction)

        # 5. Build knowledge graph in the store.
        nodes_written = 0
        for e in extraction.entities:
            if e.entity_id not in resolved_ids:
                continue
            await self._store.upsert_node(
                GraphNode(id=e.entity_id, type=e.entity_type, name=e.name,
                          properties={"confidence": e.confidence})
            )
            nodes_written += 1
        for rel in extraction.relationships:
            if rel.source_id in resolved_ids and rel.target_id in resolved_ids:
                await self._store.upsert_edge(
                    GraphEdge(id="", source_id=rel.source_id, target_id=rel.target_id,
                              type=rel.rel_type.upper(),
                              properties={"confidence": rel.confidence})
                )

        # 6. Analytics over the materialized graph.
        network = await self._store.build_network(limit=2000)
        graph = build_graph(network)
        communities = community.detect_communities(graph)
        influencers = kingpin.rank_key_entities(graph, top_k=5)
        risks = risk.risk_scores(graph)
        location_activity = loc.location_activity(records)
        bursts = tm.communication_bursts(records)

        # 7. Return a structured workflow summary.
        return {
            "scenario": scenario,
            "records_ingested": len(records),
            "entities_extracted": len(extraction.entities),
            "relationships_extracted": len(extraction.relationships),
            "resolution_candidates": [c.candidate.confidence for c in resolution_candidates],
            "graph": {"nodes": nodes_written, "edges_count": len(network.edges)},
            "analytics": {
                "communities": len(communities),
                "key_influencers": influencers[:3],
                "high_risk_count": sum(1 for r in risks if r["risk_level"] == "CRITICAL"),
                "communication_bursts": len(bursts),
                "hotspots": location_activity[:3],
            },
        }


def extract_entity_ids(extraction) -> set[str]:
    """Return the stable set of resolved entity ids (all extracted mentions)."""
    return {e.entity_id for e in extraction.entities}
