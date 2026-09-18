"""Graph / network endpoints (Phase 6)."""
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.schemas.analytics import (
    CentralityResponse,
    CommunityResponse,
    KeyEntitiesResponse,
    LinkPredictionResponse,
    RiskResponse,
)
from app.schemas.graph import GraphEdgeSchema, GraphNodeSchema, GraphResponse
from app.services.analytics_service import AnalyticsService
from app.services.graph_materializer import GraphMaterializer
from app.services.graph_service import GraphService

router = APIRouter()


@router.get(
    "/network",
    response_model=GraphResponse,
    summary="Build the network visualization graph",
)
async def build_network(
    session: DbSession,
    store: GraphStoreDep,
    _user: CurrentUser,
    node_types: Annotated[list[str] | None, Query(description="Filter by entity type")] = None,
    rel_types: Annotated[list[str] | None, Query(description="Filter by relationship type")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> GraphResponse:
    return await GraphService(store).build_network(
        node_types=node_types, rel_types=rel_types, limit=limit
    )


@router.get(
    "/entities/{entity_id}",
    response_model=GraphNodeSchema,
    summary="Get a single graph node by its entity id (e.g. P-0421)",
)
async def get_entity(
    entity_id: str,
    store: GraphStoreDep,
    _user: CurrentUser,
) -> GraphNodeSchema:
    return await GraphService(store).get_entity(entity_id)


@router.get(
    "/entities/{entity_id}/relationships",
    response_model=list[GraphEdgeSchema],
    summary="Get relationships touching an entity",
)
async def get_relationships(
    entity_id: str,
    store: GraphStoreDep,
    _user: CurrentUser,
) -> list[GraphEdgeSchema]:
    return await GraphService(store).get_relationships(entity_id)


@router.get(
    "/entities/{entity_id}/neighbors",
    response_model=list[GraphNodeSchema],
    summary="Get direct neighbors of an entity",
)
async def get_neighbors(
    entity_id: str,
    store: GraphStoreDep,
    _user: CurrentUser,
    node_types: Annotated[list[str] | None, Query()] = None,
    rel_types: Annotated[list[str] | None, Query()] = None,
) -> list[GraphNodeSchema]:
    return await GraphService(store).get_neighbors(
        entity_id, node_types=node_types, rel_types=rel_types
    )


@router.get(
    "/entities/{entity_id}/expand",
    response_model=GraphResponse,
    summary="Expand the k-hop neighborhood of an entity",
)
async def expand(
    entity_id: str,
    store: GraphStoreDep,
    _user: CurrentUser,
    depth: Annotated[int, Query(ge=1, le=5)] = 2,
    node_types: Annotated[list[str] | None, Query()] = None,
    rel_types: Annotated[list[str] | None, Query()] = None,
) -> GraphResponse:
    return await GraphService(store).expand(
        entity_id, depth=depth, node_types=node_types, rel_types=rel_types
    )


@router.post(
    "/materialize",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Materialize the graph from relational records (profiles + case links)",
)
async def materialize(
    session: DbSession,
    store: GraphStoreDep,
    user: RequireAnalyst,
) -> dict:
    summary = await GraphMaterializer(session, store).run()
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            user, "graph_refreshed", object_type="graph",
            result={"entities": summary["entities"], "edges": summary["edges"]},
        )
    except Exception:  # noqa: BLE001
        pass
    await session.commit()
    return summary


# --- Analytics (Phase 8) ----------------------------------------------------

@router.get(
    "/analytics/centrality",
    response_model=CentralityResponse,
    summary="Centrality analysis (degree, betweenness, closeness, PageRank)",
)
async def analytics_centrality(
    store: GraphStoreDep,
    _user: CurrentUser,
) -> CentralityResponse:
    return await AnalyticsService(store).centrality()


@router.get(
    "/analytics/communities",
    response_model=CommunityResponse,
    summary="Community (gang) detection + network density",
)
async def analytics_communities(
    store: GraphStoreDep,
    _user: CurrentUser,
) -> CommunityResponse:
    return await AnalyticsService(store).communities()


@router.get(
    "/analytics/key-entities",
    response_model=KeyEntitiesResponse,
    summary="Kingpin / key-influencer identification",
)
async def analytics_key_entities(
    store: GraphStoreDep,
    _user: CurrentUser,
    top_k: Annotated[int, Query(ge=1, le=100)] = 10,
) -> KeyEntitiesResponse:
    return await AnalyticsService(store).key_entities(top_k=top_k)


@router.get(
    "/analytics/link-prediction",
    response_model=LinkPredictionResponse,
    summary="Hidden link prediction (possible relationships)",
)
async def analytics_link_prediction(
    store: GraphStoreDep,
    _user: CurrentUser,
    top_k: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LinkPredictionResponse:
    return await AnalyticsService(store).link_prediction(top_k=top_k)


@router.get(
    "/analytics/risk",
    response_model=RiskResponse,
    summary="Risk scoring + anomaly detection (indicators only)",
)
async def analytics_risk(
    store: GraphStoreDep,
    _user: CurrentUser,
    anomalies: bool = True,
) -> RiskResponse:
    return await AnalyticsService(store).risk_assessment(run_anomalies=anomalies)
