"""Case data source endpoints (Phase 2-3)."""
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.repositories.case_repository import CaseRepository
from app.schemas.source import SourceCreate, SourceProcessResult, SourceRead, SourceUploadResult
from app.services.source_service import SourceService

router = APIRouter()


async def _resolve_case_id(session, case_key: str) -> int:
    repo = CaseRepository(session)
    case = await repo.get_by_case_number(case_key)
    if case is not None:
        return case.id
    if case_key.isdigit():
        c = await repo.get(int(case_key))
        if c is not None:
            return c.id
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


@router.post(
    "/{case_key}/sources/upload",
    response_model=SourceUploadResult,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a case data source file",
)
async def upload_source(
    case_key: str,
    session: DbSession,
    user: RequireAnalyst,
    file: Annotated[UploadFile, File()],
    source_type: Annotated[str, Form()],
    source_id: Annotated[str | None, Form()] = None,
) -> SourceUploadResult:
    content = await file.read()
    result = await SourceService(session).upload(case_key, source_type, file.filename, content, source_id)
    await _audit(session, user, "source_uploaded", source_id or "", {"case_key": case_key, "filename": file.filename, "format": result.format})
    await session.commit()
    return result


@router.post(
    "/{case_key}/sources",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a case data source",
)
async def register_source(
    case_key: str,
    payload: SourceCreate,
    session: DbSession,
    user: RequireAnalyst,
) -> SourceRead:
    source = await SourceService(session).register(case_key, payload)
    await _audit(session, user, "source_registered", payload.source_id, {"case_key": case_key, "source_type": payload.source_type})
    await session.commit()
    await session.refresh(source)
    return _to_read(source)


@router.get(
    "/{case_key}/sources",
    response_model=list[SourceRead],
    summary="List case data sources",
)
async def list_sources(
    case_key: str,
    session: DbSession,
    _user: CurrentUser,
) -> list[SourceRead]:
    sources = await SourceService(session).list_for_case(case_key)
    return [_to_read(s) for s in sources]


@router.post(
    "/{case_key}/sources/{source_id}/process",
    response_model=SourceProcessResult,
    summary="Process a registered source through the ingestion pipeline",
)
async def process_source(
    case_key: str,
    source_id: str,
    session: DbSession,
    store: GraphStoreDep,
    user: RequireAnalyst,
) -> SourceProcessResult:
    result = await SourceService(session).process(case_key, source_id)
    case_id = await _resolve_case_id(session, case_key)
    from app.api.v1.intelligence import invalidate_case_cache
    invalidate_case_cache(case_id)
    # Refresh the graph projection for this case so newly extracted entities
    # and relationships are visible immediately (P0.4 post-ingestion pipeline).
    from app.services.graph_materializer import GraphMaterializer
    graph_summary = await GraphMaterializer(session, store).materialize_case(case_id)
    await _audit(session, user, "source_processed", source_id, {
        "case_key": case_key,
        "records": result["record_count"],
        "entities_persisted": result["metrics"].get("entities_persisted"),
        "relationships_persisted": result["metrics"].get("relationships_persisted"),
        "graph_entities": graph_summary["entities"],
        "graph_edges": graph_summary["edges"],
        "extraction_provider": result["metrics"].get("extraction_provider", "deterministic"),
    })
    await session.commit()
    return SourceProcessResult(**result)


@router.delete(
    "/{case_key}/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a case data source",
)
async def delete_source(
    case_key: str,
    source_id: str,
    session: DbSession,
    user: RequireAnalyst,
) -> None:
    case_id = await _resolve_case_id(session, case_key)
    await SourceService(session).delete(case_key, source_id)
    from app.api.v1.intelligence import invalidate_case_cache
    invalidate_case_cache(case_id)
    await _audit(session, user, "source_deleted", source_id, {"case_key": case_key})
    await session.commit()


async def _audit(session, user, action: str, object_id: str = "", result: dict | None = None) -> None:
    """Best-effort audit write; never breaks the mutation on a logging failure."""
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(user, action, object_type="source", object_id=object_id, result=result or {})
    except Exception:  # noqa: BLE001
        pass


def _to_read(source) -> SourceRead:
    return SourceRead(
        id=source.id,
        source_id=source.source_id,
        filename=source.filename,
        file_type=source.file_type,
        source_type=source.source_type,
        status=source.status,
        record_count=source.record_count,
        processing_error=source.processing_error,
        metadata_json=source.metadata_json or {},
        uploaded_at=source.uploaded_at,
        processed_at=source.processed_at,
    )
