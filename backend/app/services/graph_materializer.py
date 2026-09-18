"""Graph materializer (Phase 6).

Builds / refreshes the knowledge graph (Neo4j) from relational records:
- every `CriminalProfile` becomes an `Entity` node
- every `case_criminals` link becomes an `INVOLVED_IN` edge to a `Case` node
- simple attribute-derived edges are created from profile attributes

This keeps the graph as a derivable projection of Postgres for the prototype.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.types import GraphEdge, GraphNode
from app.models.case import Case, CaseCriminal
from app.models.criminal import CriminalProfile
from app.models.entity import Entity, EntityRelationship


def _profile_to_node(profile: CriminalProfile) -> GraphNode:
    return GraphNode(
        id=profile.secret_id,
        type=profile.profile_type,
        name=profile.name,
        properties={
            "aliases": profile.aliases,
            "risk_score": profile.risk_score,
            "risk_level": profile.risk_level,
            "confidence": profile.confidence,
            "attributes": profile.attributes or {},
        },
    )


def _case_to_node(case: Case) -> GraphNode:
    return GraphNode(
        id=f"CS-{case.id:04d}",
        type="CASE",
        name=case.case_number or f"Case {case.id}",
        properties={"case_number": case.case_number, "status": case.status, "priority": case.priority},
    )


class GraphMaterializer:
    """Materialize the graph from relational source-of-truth records."""

    def __init__(self, session: AsyncSession, store) -> None:
        self._session = session
        self._store = store

    async def run(self) -> dict[str, int]:
        """Upsert all entities and case links into the graph store.

        Returns a small summary of what was written.
        """
        profiles_result = await self._session.execute(select(CriminalProfile))
        profiles = list(profiles_result.scalars().all())

        cases_result = await self._session.execute(select(Case))
        cases = list(cases_result.scalars().all())

        links_result = await self._session.execute(select(CaseCriminal))
        links = list(links_result.scalars().all())

        node_count = 0
        # Profiles as entity nodes
        for profile in profiles:
            await self._store.upsert_node(_profile_to_node(profile))
            node_count += 1
            # Simple attribute-derived edges (e.g. person -> organization)
            attrs = profile.attributes or {}
            org_id = attrs.get("organization_id")
            if org_id:
                await self._store.upsert_edge(
                    GraphEdge(
                        id="", source_id=profile.secret_id, target_id=org_id,
                        type="MEMBER_OF",
                        properties={"confidence": attrs.get("org_confidence", 0.8)},
                    )
                )

        # Case nodes + INVOLVED_IN edges (profiles are already nodes/created).
        for case in cases:
            await self._store.upsert_node(_case_to_node(case))
            node_count += 1

        edge_count = 0
        for link in links:
            profile = next((p for p in profiles if p.id == link.profile_id), None)
            if profile is None:
                continue
            case = next((c for c in cases if c.id == link.case_id), None)
            if case is None:
                continue
            await self._store.upsert_edge(
                GraphEdge(
                    id="",
                    source_id=profile.secret_id,
                    target_id=f"CS-{case.id:04d}",
                    type="INVOLVED_IN",
                    properties={"role": link.role_in_case or "RELATED", "confidence": 0.95},
                )
            )
            edge_count += 1

        # Extracted entities + relationships (ingested case data) -> graph.
        entities = list((await self._session.execute(select(Entity))).scalars().all())
        relationships = list((await self._session.execute(select(EntityRelationship))).scalars().all())
        extracted = await self.materialize_entities(entities, relationships)

        return {
            "entities": node_count + extracted["entities"],
            "edges": edge_count + extracted["edges"],
            "cases": len(cases),
        }

    async def materialize_case(self, case_id: int) -> dict[str, int]:
        """Upsert only ONE case's extracted entities + relationships.

        Post-ingestion pipeline: after a source is processed and persisted,
        this keeps the graph projection fresh without a full-database sweep.
        """
        entities = list((await self._session.execute(
            select(Entity).where(Entity.case_id == case_id)
        )).scalars().all())
        relationships = list((await self._session.execute(
            select(EntityRelationship).where(EntityRelationship.case_id == case_id)
        )).scalars().all())
        return await self.materialize_entities(entities, relationships)

    async def materialize_entities(self, entities: list, relationships: list) -> dict[str, int]:
        """Upsert extracted entities + relationships into the graph store."""
        node_count = 0
        for entity in entities:
            await self._store.upsert_node(
                GraphNode(
                    id=entity.entity_id,
                    type=entity.entity_type,
                    name=entity.name,
                    properties={
                        "confidence": entity.confidence,
                        "source_ids": entity.source_ids,
                        "attributes": entity.attributes,
                    },
                )
            )
            node_count += 1

        edge_count = 0
        for relationship in relationships:
            await self._store.upsert_edge(
                GraphEdge(
                    id="",
                    source_id=relationship.source_id,
                    target_id=relationship.target_id,
                    type=relationship.rel_type,
                    properties={
                        "confidence": relationship.confidence,
                        "source_ids": relationship.source_ids,
                    },
                )
            )
            edge_count += 1

        return {"entities": node_count, "edges": edge_count, "cases": 1}
