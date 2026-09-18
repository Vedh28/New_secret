"""Persisted entity + relationship endpoints (Phase 2 read path).

Read-back the canonical entities / relationships extracted from ingested
sources for a case, with provenance (source_ids) and confidence.
"""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, RequireAnalyst
from app.models.case import Case
from app.repositories.case_repository import CaseRepository
from app.repositories.entity_repository import EntityRepository, RelationshipRepository
from app.schemas.case_analytics import CommsResponse, LocationsResponse, TimelineEvent, TransResponse
from app.schemas.entity import EntityRead, EntityUpdate, RelationshipRead
from app.schemas.graph import GraphEdgeSchema, GraphNodeSchema, GraphResponse
from app.services.audit_service import AuditService
from app.services.case_analytics import CaseAnalyticsService

router = APIRouter()


async def _resolve_case(session, case_key: str) -> Case:
    repo = CaseRepository(session)
    case = await repo.get_by_case_number(case_key)
    if case is not None:
        return case
    if case_key.isdigit():
        case = await repo.get(int(case_key))
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


@router.get(
    "/{case_key}/entities",
    response_model=list[EntityRead],
    summary="Persisted entities extracted for a case",
)
async def list_case_entities(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> list[EntityRead]:
    case = await _resolve_case(session, case_key)
    rows = await EntityRepository(session).list_by_case(case.id)
    return [
        EntityRead(
            entity_id=e.entity_id,
            entity_type=e.entity_type,
            name=e.name,
            confidence=e.confidence,
            attributes=e.attributes,
            source_ids=e.source_ids,
            created_at=e.created_at,
        )
        for e in rows
    ]


@router.get(
    "/{case_key}/graph",
    response_model=GraphResponse,
    summary="Case-scoped network graph (entities + relationships of ONE case)",
)
async def case_graph(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> GraphResponse:
    """Return the graph constructed ONLY from this case's persisted data.

    PostgreSQL is the authoritative per-case source; this endpoint never mixes
    other cases or the global projection into a case screen.
    """
    case = await _resolve_case(session, case_key)
    from app.repositories.case_analytics_repo import build_case_data

    data = await build_case_data(session, case.id)
    return GraphResponse(
        nodes=[
            GraphNodeSchema(id=e.id, type=e.type, name=e.name,
                            properties={"source_ids": e.source_ids, "attributes": e.metadata})
            for e in data.entities
        ],
        edges=[
            GraphEdgeSchema(id=f"{r.source}-{r.target}-{r.rel_type}",
                            source=r.source, target=r.target, type=r.rel_type,
                            properties={"confidence": r.confidence, "source_ids": r.source_ids})
            for r in data.relationships
        ],
    )


@router.patch(
    "/{case_key}/entities/{entity_id}",
    response_model=EntityRead,
    summary="Resolve or update a canonical case entity",
)
async def update_case_entity(
    case_key: str,
    entity_id: str,
    payload: EntityUpdate,
    session: DbSession,
    user: RequireAnalyst,
) -> EntityRead:
    if payload.location_name and (payload.latitude is None or payload.longitude is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter both latitude and longitude to save a location",
        )
    case = await _resolve_case(session, case_key)
    repo = EntityRepository(session)
    entity = await repo.get_any_type(case.id, entity_id)
    if entity is None:
        if not entity_id.upper().startswith("UNKNOWN-"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
        # A disclosure may identify an entity before a dedicated canonical row exists.
        entity = await repo.create(
            case_id=case.id,
            entity_id=entity_id,
            entity_type="PERSON",
            name=entity_id,
            confidence=0.0,
            attributes={},
            source_ids=[],
        )

    previous_name = entity.name
    attributes = dict(entity.attributes or {})
    resolution = dict(attributes.get("identity_resolution") or {})
    resolution.update({
        "previous_name": resolution.get("previous_name") or previous_name,
        "resolved_name": payload.name,
        "note": payload.note or resolution.get("note"),
        "source_ids": payload.source_ids,
        "status": "RESOLVED",
    })
    entity.name = payload.name
    entity.confidence = payload.confidence
    entity.source_ids = list(dict.fromkeys([*(entity.source_ids or []), *payload.source_ids]))
    entity.attributes = {**attributes, "identity_resolution": resolution}
    await repo.save(entity)
    if payload.location_name:
        location_id = f"LOCATION:{payload.location_name.strip().lower()}"
        location = await repo.get_any_type(case.id, location_id)
        if location is None:
            location = await repo.create(
                case_id=case.id,
                entity_id=location_id,
                entity_type="LOCATION",
                name=payload.location_name.strip(),
                confidence=payload.confidence,
                attributes={
                    "latitude": payload.latitude,
                    "longitude": payload.longitude,
                    "source_ids": payload.source_ids,
                },
                source_ids=payload.source_ids,
            )
        else:
            location.name = payload.location_name.strip()
            location.confidence = max(location.confidence, payload.confidence)
            location.attributes = {
                **(location.attributes or {}),
                "latitude": payload.latitude,
                "longitude": payload.longitude,
            }
            location.source_ids = list(dict.fromkeys([*(location.source_ids or []), *payload.source_ids]))
            await repo.save(location)
        rel_repo = RelationshipRepository(session)
        relation = await rel_repo.get(case.id, "LOCATED_AT", entity_id, location_id)
        if relation is None:
            await rel_repo.create(
                case_id=case.id,
                rel_type="LOCATED_AT",
                source_id=entity_id,
                target_id=location_id,
                confidence=payload.confidence,
                source_ids=payload.source_ids,
                attributes={"latitude": payload.latitude, "longitude": payload.longitude},
            )
    await AuditService(session).record(
        user=user,
        action="resolve_identity",
        object_type="entity",
        object_id=f"{case.case_number}:{entity_id}",
        result={"previous_name": previous_name, "resolved_name": payload.name, "source_ids": payload.source_ids, "location": payload.location_name},
    )
    await session.commit()
    return EntityRead(
        entity_id=entity.entity_id,
        entity_type=entity.entity_type,
        name=entity.name,
        confidence=entity.confidence,
        attributes=entity.attributes or {},
        source_ids=entity.source_ids or [],
        created_at=entity.created_at,
    )


@router.get(
    "/{case_key}/relationships",
    response_model=list[RelationshipRead],
    summary="Persisted relationships extracted for a case",
)
async def list_case_relationships(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> list[RelationshipRead]:
    case = await _resolve_case(session, case_key)
    rows = await RelationshipRepository(session).list_by_case(case.id)
    return [
        RelationshipRead(
            rel_type=r.rel_type,
            source_id=r.source_id,
            target_id=r.target_id,
            confidence=r.confidence,
            source_ids=r.source_ids,
            attributes=r.attributes,
            created_at=r.created_at,
        )
        for r in rows
    ]


# --- Per-case analysis (comms / transactions / timeline / locations) -----------

@router.get(
    "/{case_key}/communications",
    response_model=CommsResponse,
    summary="Communication analysis from persisted CDR relationships",
)
async def case_communications(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> CommsResponse:
    case = await _resolve_case(session, case_key)
    return CommsResponse(**await CaseAnalyticsService(session).communications(case.id))


@router.get(
    "/{case_key}/transactions",
    response_model=TransResponse,
    summary="Transaction analysis from persisted transfer edges",
)
async def case_transactions(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> TransResponse:
    case = await _resolve_case(session, case_key)
    return TransResponse(**await CaseAnalyticsService(session).transactions(case.id))


@router.get(
    "/{case_key}/timeline",
    response_model=list[TimelineEvent],
    summary="Unified case timeline from all ingested sources",
)
async def case_timeline(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> list[TimelineEvent]:
    case = await _resolve_case(session, case_key)
    return [TimelineEvent(**e) for e in await CaseAnalyticsService(session).timeline(case.id)]


@router.get(
    "/{case_key}/locations",
    response_model=LocationsResponse,
    summary="Location intelligence from ingested location entities",
)
async def case_locations(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> LocationsResponse:
    case = await _resolve_case(session, case_key)
    return LocationsResponse(**await CaseAnalyticsService(session).locations(case.id))
