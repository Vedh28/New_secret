"""GraphService unit tests (Phase 6).

Exercise the service + in-memory graph store without requiring Neo4j.
"""
import pytest

from app.graph.memory_store import MemoryGraphStore
from app.graph.types import GraphEdge, GraphNode
from app.services.graph_service import GraphService
from fastapi import HTTPException


def _seed(store: MemoryGraphStore) -> None:
    """Create a small deterministic network."""
    p = GraphNode(id="P-0421", type="PERSON", name="Person A", properties={"risk": 94})
    p2 = GraphNode(id="P-0182", type="PERSON", name="Person B", properties={"risk": 71})
    o = GraphNode(id="O-1101", type="ORGANIZATION", name="Org Orion", properties={})
    v = GraphNode(id="V-2048", type="VEHICLE", name="Vehicle VX", properties={})
    for node in (p, p2, o, v):
        store.nodes[node.id] = node
    store.edges["E1"] = GraphEdge(id="E1", source_id="P-0421", target_id="O-1101", type="MEMBER_OF")
    store.edges["E2"] = GraphEdge(id="E2", source_id="P-0421", target_id="V-2048", type="OWNS")
    store.edges["E3"] = GraphEdge(id="E3", source_id="P-0182", target_id="O-1101", type="MEMBER_OF")


@pytest.mark.asyncio
async def test_get_entity_returns_node() -> None:
    store = MemoryGraphStore()
    _seed(store)
    service = GraphService(store)
    node = await service.get_entity("P-0421")
    assert node.id == "P-0421"
    assert node.type == "PERSON"


@pytest.mark.asyncio
async def test_get_entity_missing_404() -> None:
    service = GraphService(MemoryGraphStore())
    with pytest.raises(HTTPException) as exc:
        await service.get_entity("P-9999")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_neighbors_filters_by_type() -> None:
    store = MemoryGraphStore()
    _seed(store)
    service = GraphService(store)
    neighbors = await service.get_neighbors("P-0421", node_types=["ORGANIZATION"])
    ids = [n.id for n in neighbors]
    assert ids == ["O-1101"]


@pytest.mark.asyncio
async def test_expand_neighborhood_distance_2() -> None:
    store = MemoryGraphStore()
    _seed(store)
    service = GraphService(store)
    # P-0421 -> (Org Orion, Vehicle); Org -> P-0182 at depth 2
    result = await service.expand("P-0421", depth=2)
    node_ids = {n.id for n in result.nodes}
    assert "P-0182" in node_ids
    assert "O-1101" in node_ids
    assert "V-2048" in node_ids


@pytest.mark.asyncio
async def test_build_network_filters_by_type() -> None:
    store = MemoryGraphStore()
    _seed(store)
    service = GraphService(store)
    result = await service.build_network(node_types=["ORGANIZATION"])
    assert [n.id for n in result.nodes] == ["O-1101"]


@pytest.mark.asyncio
async def test_get_relationships() -> None:
    store = MemoryGraphStore()
    _seed(store)
    service = GraphService(store)
    rels = await service.get_relationships("P-0421")
    types = {e.type for e in rels}
    assert types == {"MEMBER_OF", "OWNS"}

class TestCypherLabelSanitizer:
    """Data-driven node/edge types are interpolated into Cypher; anything that
    is not a bare [A-Za-z0-9_] token must fall back to a safe default."""

    @pytest.fixture()
    def safe(self):
        from app.graph.neo4j_store import _safe_label
        return _safe_label

    def test_normal_labels_pass_through(self, safe):
        assert safe("PERSON", "Entity") == "PERSON"
        assert safe("CDR_X1", "Entity") == "CDR_X1"
        assert safe("MEMBER_OF", "Entity") == "MEMBER_OF"

    def test_injection_tokens_fall_back(self, safe):
        for attack in (") MERGE (n:EVIL {id:'x'}) //", "P)(n)-[:R]->", "A; MATCH (x)",
                       "`PERSON`", "PERSON:TOO", "PERSON}):X", "hei`ght", "plain space"):
            assert safe(attack, "Entity") == "Entity"

    def test_empty_and_weird_types_fall_back(self, safe):
        assert safe(None, "Entity") == "Entity"
        assert safe("", "Entity") == "Entity"
        assert safe("123", "Entity") == "Entity"  # must start with a letter
        assert safe({}, "Entity") == "Entity"
        assert safe(42, "Entity") == "Entity"
