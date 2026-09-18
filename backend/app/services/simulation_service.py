"""Demo mode / simulation service (original Phase 15).

Runs the full intelligence pipeline step-by-step and returns a structured,
UI-friendly result: generate -> ingest -> extract -> resolve -> graph ->
analytics -> anomalies -> insights. Each step is reported so the UI can animate
the progress.
"""
from __future__ import annotations

import time

from app.analytics import community, kingpin, risk
from app.analytics.graph_builder import build_graph
from app.ingestion.adapters import normalize_record
from app.ingestion.generator import ALL_SCENARIOS, generate_synthetic
from app.ingestion.providers import get_extraction_provider
from app.ingestion.resolution import resolve


class SimulationService:
    """Orchestrate the demo simulation and produce its output."""

    def __init__(self, store) -> None:
        self._store = store

    async def run(self, scenario: str = "NORMAL_NETWORK") -> dict:
        started = time.time()
        steps: list[dict] = []

        # 1. Generate synthetic records.
        raw = generate_synthetic(scenario)
        steps.append(self._step("Generate synthetic records", len(raw), raw))

        # 2. Ingest / normalize.
        records = [
            normalize_record(r.source_type, {"id": r.record_id, "timestamp": r.timestamp, "text": r.text, **r.fields})
            for r in raw
        ]
        steps.append(self._step("Ingest & normalize", len(records), records))

        # 3. Extract entities + relationships.
        extraction = get_extraction_provider().extract(records)
        steps.append(
            self._step("Extract entities", len(extraction.entities),
                       extraction.entities)
        )

        # 4. Resolve possible duplicates.
        known: dict[str, list[str]] = {e.entity_id: [e.name] for e in extraction.entities}
        candidates = resolve(known, extraction.entities)
        steps.append(self._step("Entity resolution", len(candidates), candidates))

        # 5. Build knowledge graph.
        for e in extraction.entities:
            await self._store.upsert_node(
                __import__("app.graph.types", fromlist=["GraphNode"]).GraphNode(
                    id=e.entity_id, type=e.entity_type, name=e.name,
                    properties={"confidence": e.confidence}
                )
            )
        for rel in extraction.relationships:
            await self._store.upsert_edge(
                __import__("app.graph.types", fromlist=["GraphEdge"]).GraphEdge(
                    id="", source_id=rel.source_id, target_id=rel.target_id,
                    type=rel.rel_type.upper(), properties={"confidence": rel.confidence}
                )
            )
        network = await self._store.build_network(limit=2000)
        steps.append(self._step("Build knowledge graph", len(network.nodes), network))

        # 6. Graph analytics.
        graph = build_graph(network)
        communities = community.detect_communities(graph)
        influencers = kingpin.rank_key_entities(graph, top_k=5)
        steps.append(self._step("Graph analytics", len(communities), {"communities": len(communities)}))

        # 7. Anomaly detection.
        scores = risk.risk_scores(graph)
        anomalies = risk.isolation_forest_anomalies(graph)
        steps.append(self._step("Anomaly detection", len(anomalies), anomalies))

        # 8. Insights.
        insights = {
            "communities": len(communities),
            "key_influencers": [i["entity_id"] for i in influencers[:3]],
            "critical_risk": sum(1 for r in scores if r["risk_level"] == "CRITICAL"),
            "anomalies": anomalies,
        }
        steps.append(self._step("Generate insights", len(insights), insights))

        elapsed = round(time.time() - started, 3)
        return {
            "scenario": scenario,
            "steps": steps,
            "entities": len(extraction.entities),
            "relationships": len(extraction.relationships),
            "nodes_written": len(network.nodes),
            "insights": insights,
            "elapsed_seconds": elapsed,
        }

    def _step(self, label: str, count: int, payload) -> dict:
        return {"label": label, "count": count, "sample": str(payload)[:120]}


def scenarios() -> list[str]:
    return list(ALL_SCENARIOS)
