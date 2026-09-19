"""Integration tests for database / graph connectivity.

Marked by dependency so each service is probed independently (PostgreSQL tests
run even when Neo4j is down, and vice versa). Skipped automatically when the
required external service is unreachable.

Run with real services:
    pytest -m integration_pg         # PostgreSQL only
    pytest -m integration_neo4j      # Neo4j only
    pytest -m integration            # both
"""
import pytest

from app.core.dbcheck import check_database_connection
from app.core.graphcheck import check_graph_connection


@pytest.mark.integration_pg
@pytest.mark.asyncio
async def test_postgres_reachable() -> None:
    result = await check_database_connection()
    assert result["status"] == "ok", f"PostgreSQL unreachable: {result}"


@pytest.mark.integration_neo4j
@pytest.mark.asyncio
async def test_neo4j_reachable() -> None:
    result = await check_graph_connection()
    assert result["status"] == "ok", f"Neo4j unreachable: {result}"
