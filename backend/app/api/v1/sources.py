"""Case data source endpoints (Phase 2-3)."""
import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.repositories.case_repository import CaseRepository
from app.schemas.source import SourceCreate, SourceProcessResult, SourceRead, SourceUploadResult
from app.services.source_service import SourceService

logger = logging.getLogger("secret.integrity")

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
    case_id = await _resolve_case_id(session, case_key)
    await _audit(session, user, "source_uploaded", result.source_id, {
        "case_key": case_key, "filename": file.filename, "format": result.format,
        "evidence_hash": result.evidence_hash,
    })
    # Commit the AUTHORITATIVE upload transaction BEFORE best-effort integrity,
    # so any integrity failure can never poison the source's transaction.
    await session.commit()

    integrity_status = await _register_evidence_integrity_isolated(
        case_id, file.filename, source_type, result.source_id,
        result.evidence_hash or "", user.id)
    result.integrity_status = integrity_status
    return result


async def _register_evidence_integrity_isolated(case_id: int, filename: str, source_type: str,
                                                source_id: str, evidence_hash: str,
                                                actor_id: int) -> str:
    """Register the source's integrity fingerprint in its OWN transaction."""
    from app.blockchain.isolated import run_integrity_isolated

    async def _builder(session):
        from app.blockchain.hashes import canonical_evidence_payload, hash_evidence_payload
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.source_repository import SourceRepository

        row = next((s for s in await SourceRepository(session).list_by_case(case_id)
                    if s.source_id == source_id), None)
        meta = row.metadata_json or {} if row else {}
        records = [r for r in (meta.get("records") or []) if isinstance(r, dict)]
        content_hash = hash_evidence_payload(canonical_evidence_payload(
            case_id=case_id, source_id=source_id, source_type=source_type,
            filename=filename, records=records, text=str(meta.get("text") or ""),
        ))
        registered = await BlockchainIntegrityService(session).register_evidence(
            case_id=case_id, source_id=source_id, source_type=source_type,
            filename=filename, evidence_hash=evidence_hash, content_hash=content_hash,
            actor_id=actor_id,
        )
        return registered.get("status", "REGISTERED")

    ok, status, error = await run_integrity_isolated(_builder)
    if not ok:
        logger.warning("evidence registration failed case=%s source=%s type=%s",
                       case_id, source_id, type(error).__name__ if error else "unknown")
        return "LEDGER_UNAVAILABLE"
    return status or "LEDGER_UNAVAILABLE"


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
    # and relationships are visible immediately (P0.4/P1-10 pipeline). Any
    # failure here aborts the commit so Postgres and the projection stay
    # coherent — the caller sees a clear error, never a silently "ready" state.
    from app.services.graph_materializer import GraphMaterializer
    try:
        graph_summary = await GraphMaterializer(session, store).materialize_case(case_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Source processed but the graph refresh failed; the transaction was rolled back. Fix the graph store and retry.",
        ) from exc
    await _audit(session, user, "source_processed", source_id, {
        "case_key": case_key,
        "records": result["record_count"],
        "entities_persisted": result["metrics"].get("entities_persisted"),
        "relationships_persisted": result["metrics"].get("relationships_persisted"),
        "graph_entities": graph_summary["entities"],
        "graph_edges": graph_summary["edges"],
        "extraction_provider": result["metrics"].get("extraction_provider", "deterministic"),
    })
    # Commit the AUTHORITATIVE processing transaction (parsed + persisted +
    # graph materialized). Integrity batching runs AFTER, in its own session/DB
    # transaction, so a ledger failure can never poison processing results.
    await session.commit()

    batch, batch_ok = await _register_batch_isolated(case_id, source_id, result["metrics"], user.id)
    integrity_status = "REGISTERED" if batch.get("transaction_id") else (
        "PENDING" if batch.get("merkle_root") is not None else "LEDGER_UNAVAILABLE"
    )
    if batch.get("transaction_id"):
        await _enrich_provenance_isolated(case_id, source_id, batch)

    metrics = {
        **result["metrics"],
        "graph_refreshed": True,
        "graph_entities": graph_summary["entities"],
        "graph_edges": graph_summary["edges"],
        "merkle_root": batch.get("merkle_root"),
        "integrity_tx": batch.get("transaction_id"),
        "integrity_block": batch.get("block_index"),
        "integrity_status": integrity_status,
    }
    return SourceProcessResult(**{**result, "metrics": metrics})


async def _register_batch_isolated(case_id: int, source_id: str, metrics: dict,
                                   actor_id: int) -> tuple[dict, bool]:
    """Register processed records as a batched Merkle integrity event in its
    own transaction (reads the committed source row from its own session)."""
    from app.blockchain.isolated import run_integrity_isolated

    async def _builder(session):
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.source_repository import SourceRepository

        row = next((s for s in await SourceRepository(session).list_by_case(case_id)
                    if s.source_id == source_id), None)
        records = [r for r in (row.metadata_json or {}).get("records", []) if isinstance(r, dict)] if row else []
        return await BlockchainIntegrityService(session).register_processed_batch(
            case_id=case_id, source_id=source_id, source_type=(row.source_type if row else "OTHER"),
            records=records, actor_id=actor_id,
            extraction={"entities": metrics.get("entities_persisted", 0),
                        "relationships": metrics.get("relationships_persisted", 0)},
        )

    ok, batch, error = await run_integrity_isolated(_builder)
    if not ok:
        logger.warning("processed-batch registration failed case=%s source=%s type=%s",
                       case_id, source_id, type(error).__name__ if error else "unknown")
        return {}, False
    return batch or {}, True


async def _enrich_provenance_isolated(case_id: int, source_id: str, batch: dict) -> None:
    """Best-effort: stamp the ledger tx/block onto committed source provenance."""
    from app.blockchain.isolated import run_integrity_isolated

    async def _builder(session):
        from app.repositories.source_repository import SourceRepository

        rows = await SourceRepository(session).list_by_case(case_id)
        row = next((s for s in rows if s.source_id == source_id), None)
        if row is None:
            return
        provenance = row.metadata_json.get("provenance") or []
        for item in provenance:
            item["transaction_id"] = batch["transaction_id"]
            item["block_index"] = batch["block_index"]
        row.metadata_json = {
            **row.metadata_json,
            "provenance": provenance,
            "integrity_tx": batch["transaction_id"],
            "integrity_block": batch["block_index"],
            "merkle_root": batch.get("merkle_root"),
        }
        await SourceRepository(session).save(row)

    ok, _r, error = await run_integrity_isolated(_builder)
    if not ok:
        logger.warning("provenance enrichment failed case=%s source=%s type=%s",
                       case_id, source_id, type(error).__name__ if error else "unknown")


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
    except Exception as exc:  # noqa: BLE001 - best-effort audit
        logger.warning("source audit failed action=%s source=%s type=%s",
                       action, object_id, type(exc).__name__)


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
