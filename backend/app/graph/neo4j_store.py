"""Neo4j graph store (Phase 6).

Production implementation of `GraphStore` backed by Neo4j. Uses the async
driver singleton from `app.core.neo4j`. All queries operate on the property-graph
schema defined in `cypher/schema.cypher`.
"""
from typing import Any

from app.core.neo4j import neo4j_connection
from app.graph.types import GraphEdge, GraphNode, GraphSubgraph

import json
import re

# Properties Neo4jStore is allowed to write on nodes/edges. Everything else is
# intentionally dropped (configuration denies arbitrary property keys).
_NODE_PROPS = {
    "aliases", "risk_score", "risk_level", "confidence", "attributes", "source_ids",
    "status", "priority", "case_number", "latitude", "longitude", "area",
}
_EDGE_PROPS = {
    "confidence", "source_ids", "amount", "role", "first_seen", "last_seen", "strength",
}


def _render_set(prefix: str, properties: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for key, value in properties.items():
        value = _neo4j_value(value)
        if value is None:
            continue
        clauses.append(f"{prefix}.{key} = ${key}")
        params[key] = value
    return (", " + ", ".join(clauses)) if clauses else "", params


def _neo4j_value(value: Any) -> Any:
    """Neo4j allows only primitives / arrays. Flatten or stringify the rest."""
    if isinstance(value, (int, float, bool, str)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_neo4j_value(v) for v in value]
    if isinstance(value, dict):
        # Empty maps are valid; non-empty need flattening or key-dropping.
        return json.dumps(value)
    return str(value)


# Only safe, injectable-proof label/rel-type tokens are ever interpolated into
# Cypher. Everything else falls back to a fixed default so a data-driven type
# can never inject query text.
_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def _safe_label(value: Any, default: str) -> str:
    token = str(value or "")
    return token if _LABEL_RE.fullmatch(token) else default


def _record_key(record) -> str:
    """Best-effort node id from a Neo4j record."""
    for key in ("id", "entity_id", "secret_id"):
        val = record.get(key)
        if val is not None:
            return str(val)
    return str(record.get("identity", ""))


def _to_node(record) -> GraphNode | None:
    props = dict(record.get("n") or {})
    node_id = props.get("id") or record.get("id")
    if node_id is None:
        node_id = _record_key(record)
        if not node_id:
            return None
    node_type = str(props.get("type") or record.get("type") or "ENTITY")
    name = str(props.get("name") or props.get("full_name") or node_id)
    return GraphNode(id=str(node_id), type=node_type, name=name, properties=props)


def _to_edge(record, source_key: str = "a", target_key: str = "b", rel_key: str = "r") -> GraphEdge | None:
    rel = record.get(rel_key)
    source = record.get(source_key)
    target = record.get(target_key)
    if rel is None:
        return None
    # Prefer embedded properties; fall back to element metadata.
    rel_props = dict(rel) if hasattr(rel, "items") else {}
    source_id = (getattr(source, "element_id", None) if source is not None else None) \
        or (rel_props.get("source_id") if "source_id" in rel_props else "")
    target_id = (getattr(target, "element_id", None) if target is not None else None) \
        or (rel_props.get("target_id") if "target_id" in rel_props else "")
    rel_type = str(rel.type) if hasattr(rel, "type") else str(rel_props.get("type", "ASSOCIATED_WITH"))
    edge_id = getattr(rel, "element_id", None) or f"{source_id}-{rel_type}-{target_id}"
    return GraphEdge(
        id=str(edge_id),
        source_id=str(source_id),
        target_id=str(target_id),
        type=rel_type,
        properties=rel_props,
    )


class Neo4jStore:
    """Production `GraphStore` implementation backed by Neo4j."""

    async def _run(self, query: str, **params) -> list[dict[str, Any]]:
        driver = neo4j_connection.driver
        async with driver.session() as session:
            result = await session.run(query, **params)
            return await result.data()

    # --- reads ---

    async def get_entity(self, entity_id: str) -> GraphNode | None:
        rows = await self._run(
            "MATCH (n:Entity {id: $id}) RETURN n, labels(n) AS type LIMIT 1",
            id=entity_id,
        )
        if not rows:
            return None
        row = rows[0]
        labels = row.get("type") or []
        entity_label = next((l for l in labels if l != "Entity"), "ENTITY")
        node = _to_node({**row, "type": entity_label})
        return node

    async def get_relationships(self, entity_id: str) -> list[GraphEdge]:
        rows = await self._run(
            """
            MATCH (n:Entity {id: $id})-[r]-(m)
            RETURN id(r) AS rid, r AS r, n AS a, m AS b, type(r) AS rel_type
            """,
            id=entity_id,
        )
        edges: list[GraphEdge] = []
        for row in rows:
            edge = _to_edge(row)
            if edge:
                edges.append(edge)
        return edges

    async def get_neighbors(
        self,
        entity_id: str,
        node_types: list[str] | None = None,
        rel_types: list[str] | None = None,
    ) -> list[GraphNode]:
        conditions: list[str] = []
        params: dict[str, Any] = {"id": entity_id}
        if node_types:
            conditions.append("m:Entity")
            # Without indexes on per-label ids this is approximated via labels.
        if rel_types:
            params["rel_types"] = rel_types
            conditions.append("type(r) IN $rel_types")
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self._run(
            f"""
            MATCH (n:Entity {{id: $id}})-[r]-(m)
            {where_clause}
            RETURN m AS n, labels(m) AS type
            """,
            **params,
        )
        nodes: list[GraphNode] = []
        seen: set[str] = set()
        for row in rows:
            labels = row.get("type") or []
            labels = [l for l in labels if l != "Entity"]
            entity_label = next(iter(labels), "ENTITY")
            if node_types and entity_label not in node_types:
                continue
            node = _to_node({**row, "type": entity_label})
            if node and node.id not in seen:
                seen.add(node.id)
                nodes.append(node)
        return nodes

    async def expand_neighborhood(
        self,
        entity_id: str,
        depth: int = 1,
        node_types: list[str] | None = None,
        rel_types: list[str] | None = None,
    ) -> GraphSubgraph:
        params: dict[str, Any] = {"id": entity_id}
        rel_clause = ""
        if rel_types:
            params["rel_types"] = rel_types
            rel_clause = "AND type(r) IN $rel_types"
        nodes: dict[str, GraphNode] = {}
        edges: dict[str, GraphEdge] = {}
        edge_ids: set[str] = set()
        frontier = {entity_id}
        visited: set[str] = set()

        for _ in range(max(1, depth)):
            next_frontier: set[str] = set()
            for current in frontier:
                if current in visited:
                    continue
                visited.add(current)
                if current not in nodes:
                    node = await self.get_entity(current)
                    if node:
                        nodes[current] = node
                rows = await self._run(
                    f"""
                    MATCH (n:Entity {{id: $id}})-[r]-(m)
                    {rel_clause}
                    RETURN m AS m, r AS r, n AS n
                    """,
                    **params,
                )
                for row in rows:
                    edge = _to_edge(row)
                    if edge is None:
                        continue
                    key = f"{edge.source_id}|{edge.target_id}|{edge.type}"
                    if key not in edge_ids:
                        edge_ids.add(key)
                        edges[key] = edge
                    neighbor_id = _record_key(row.get("m") or row)
                    if neighbor_id:
                        next_frontier.add(neighbor_id)
            frontier = next_frontier

        if node_types:
            node_types = set(node_types)
            nodes = {nid: n for nid, n in nodes.items() if n.type in node_types}

        return GraphSubgraph(nodes=list(nodes.values()), edges=list(edges.values()))

    async def build_network(
        self,
        node_types: list[str] | None = None,
        rel_types: list[str] | None = None,
        limit: int = 500,
    ) -> GraphSubgraph:
        params: dict[str, Any] = {"limit": limit}
        node_filter = ""
        if node_types:
            params["node_types"] = node_types
            node_filter = "WHERE any(l IN labels(n) WHERE l IN $node_types)"
        rows = await self._run(
            f"""
            MATCH (n)
            {node_filter}
            RETURN n
            LIMIT $limit
            """,
            **params,
        )
        nodes: list[GraphNode] = []
        ids: set[str] = set()
        for row in rows:
            node = _to_node({**row, "type": None})
            if node:
                ids.add(node.id)
                nodes.append(node)
        rel_filter = ""
        if rel_types:
            params["rel_types"] = rel_types
            rel_filter = "AND type(r) IN $rel_types"
        edge_rows = await self._run(
            f"""
            MATCH (a)-[r]->(b)
            WHERE a.id IN $ids AND b.id IN $ids {rel_filter}
            RETURN a, r, b
            LIMIT $limit
            """,
            **{**params, "ids": list(ids)},
        )
        edges: list[GraphEdge] = []
        for row in edge_rows:
            edge = _to_edge(row, "a", "b", "r")
            if edge:
                edges.append(edge)
        return GraphSubgraph(nodes=nodes, edges=edges)

    # --- mutations (used by materialization service) ---

    async def upsert_node(self, node: GraphNode) -> None:
        label = _safe_label(node.type, "Entity")
        props = {k: v for k, v in (node.properties or {}).items() if k in _NODE_PROPS}
        set_clause, prop_params = _render_set("n", props)
        await self._run(
            f"""
            MERGE (n:{label} {{id: $id}})
            SET n.name = $name, n.type = $type, n.updated_at = datetime(){set_clause}
            """,
            id=node.id,
            name=node.name,
            type=node.type,
            **prop_params,
        )

    async def upsert_edge(self, edge: GraphEdge) -> None:
        props = {k: v for k, v in (edge.properties or {}).items() if k in _EDGE_PROPS}
        rel_type = _safe_label(edge.type, "LINKED_WITH")
        set_clause, prop_params = _render_set("r", props)
        await self._run(
            f"""
            MATCH (a {{id: $source_id}})
            MATCH (b {{id: $target_id}})
            MERGE (a)-[r:{rel_type}]->(b)
            SET r.updated_at = datetime(){set_clause}
            """,
            source_id=edge.source_id,
            target_id=edge.target_id,
            **prop_params,
        )
