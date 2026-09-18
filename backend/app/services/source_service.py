"""Source service (Phase 2-3)."""
import asyncio
import hashlib
import os
import re
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.ingestion.adapters import normalize_record
from app.ingestion.parsers import parse_source
from app.ingestion.providers import get_extraction_provider
from app.models.source import Source
from app.repositories.case_repository import CaseRepository
from app.repositories.entity_repository import EntityRepository, RelationshipRepository
from app.repositories.source_repository import SourceRepository
from app.schemas.source import SourceUploadResult


class SourceService:
    """Register, list, delete and process case data sources."""

    def __init__(self, session) -> None:
        self._repo = SourceRepository(session)
        self._cases = CaseRepository(session)
        self._entities = EntityRepository(session)
        self._relationships = RelationshipRepository(session)

    async def _case(self, case_key: str) -> int:
        case = await self._cases.get_by_case_number(case_key)
        if case is not None:
            return case.id
        if case_key.isdigit():
            c = await self._cases.get(int(case_key))
            if c is not None:
                return c.id
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    async def register(self, case_key: str, payload) -> Source:
        case_id = await self._case(case_key)
        existing = await self._repo.get_by_case_and_source(case_id, payload.source_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=f"Source {payload.source_id} already registered"
            )
        return await self._repo.create(
            case_id=case_id,
            source_id=payload.source_id,
            filename=payload.filename,
            file_type=payload.file_type,
            source_type=payload.source_type,
            record_count=payload.record_count,
            status="UPLOADED",
            metadata_json=payload.payload,
        )

    async def list_for_case(self, case_key: str) -> list[Source]:
        case_id = await self._case(case_key)
        return await self._repo.list_by_case(case_id)

    async def delete(self, case_key: str, source_id: str) -> None:
        case_id = await self._case(case_key)
        source = await self._repo.get_by_case_and_source(case_id, source_id)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
        await self._repo.delete(source)

    async def upload(
        self,
        case_key: str,
        source_type: str,
        filename: str,
        content: bytes,
        source_id: str | None = None,
    ) -> SourceUploadResult:
        """Real file upload: hash-dedupe, parse, validate, and persist a source."""
        case_id = await self._case(case_key)

        if len(content) > get_settings().max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds maximum upload size",
            )

        safe_name = _sanitize_filename(filename)
        digest = hashlib.sha256(content).hexdigest()
        existing = await self._repo.list_by_case(case_id)
        for s in existing:
            if (s.metadata_json or {}).get("sha256") == digest:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Duplicate upload: file already ingested as {s.source_id}",
                )

        if source_id is None:
            source_id = _slugify(safe_name)
        if any(s.source_id == source_id for s in existing):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Source {source_id} already registered",
            )

        parsed = await asyncio.to_thread(parse_source, safe_name, content, source_type)

        payload = {
            "format": parsed.format,
            "sha256": digest,
            "quality": parsed.quality,
            "records": parsed.records,
            "text": parsed.raw_text,
        }
        status_label = "ERROR" if parsed.error else "READY"
        source = await self._repo.create(
            case_id=case_id,
            source_id=source_id,
            filename=safe_name,
            file_type=parsed.format,
            source_type=source_type,
            record_count=len(parsed.records) if not parsed.error else 0,
            status=status_label,
            processing_error=parsed.error,
            metadata_json=payload,
        )
        return SourceUploadResult(
            source_id=source.source_id,
            filename=source.filename,
            case_id=source.case_id,
            format=parsed.format,
            status=source.status,
            record_count=len(parsed.records),
            quality=parsed.quality,
            error=parsed.error,
        )

    async def process(self, case_key: str, source_id: str) -> dict:
        """Run the real ingestion pipeline over the source payload."""
        case_id = await self._case(case_key)
        source = await self._repo.get_by_case_and_source(case_id, source_id)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

        payload = source.metadata_json or {}
        raw_records = payload.get("records", [])
        text = payload.get("text", "")

        records = []
        if raw_records:
            for raw in raw_records:
                try:
                    records.append(
                        normalize_record(
                            source.source_type or str(raw.get("source_type", "OTHER")),
                            {"id": str(raw.get("id", "")), "timestamp": str(raw.get("timestamp", "")),
                             "text": str(raw.get("text", "")), **raw.get("fields", {})},
                        )
                    )
                except Exception:  # noqa: BLE001
                    continue
        elif text:
            records.append(
                normalize_record(
                    source.source_type or "OTHER",
                    {"id": source.source_id, "timestamp": "", "text": text, **payload},
                )
            )

        extraction_provider = get_extraction_provider(get_settings().extraction_provider)
        extraction = extraction_provider.extract(records)
        entity_map, relationship_map = await self._persist_extraction(case_id, source_id, extraction)
        metrics = {
            "records_processed": len(records),
            "entities_extracted": len(extraction.entities),
            "relationships_extracted": len(extraction.relationships),
            "entities_persisted": len(entity_map),
            "relationships_persisted": len(relationship_map),
            "extraction_provider": extraction_provider.name,
        }

        source.status = "PROCESSED"
        source.record_count = len(records)
        source.processed_at = datetime.now(timezone.utc)
        source.metadata_json = {**source.metadata_json, "metrics": metrics}
        await self._repo.save(source)

        return {
            "source_id": source.source_id,
            "filename": source.filename,
            "case_id": source.case_id,
            "status": source.status,
            "record_count": len(records),
            "metrics": metrics,
        }

    async def _persist_extraction(self, case_id: int, source_id: str, extraction) -> tuple[dict, dict]:
        """Persist extracted mentions, merging by (case, identity, type)."""
        existing_entities = await self._entities.list_by_case(case_id)
        entity_map = {(e.entity_id, e.entity_type): e for e in existing_entities}
        existing_rels = await self._relationships.list_by_case(case_id)
        rel_map = {(r.rel_type, r.source_id, r.target_id): r for r in existing_rels}

        for mention in extraction.entities:
            key = (mention.entity_id, mention.entity_type.upper())
            row = entity_map.get(key)
            if row is None:
                row = await self._entities.create(
                    case_id=case_id,
                    entity_id=mention.entity_id,
                    entity_type=mention.entity_type.upper(),
                    name=mention.name,
                    confidence=mention.confidence,
                    attributes={},
                    source_ids=[source_id],
                )
                entity_map[key] = row
            elif source_id not in row.source_ids:
                row.confidence = max(row.confidence, mention.confidence)
                _merge_source_ids(row.source_ids, source_id)
                await self._entities.save(row)

        for mention in extraction.relationships:
            rel_type = mention.rel_type.upper()
            key = (rel_type, mention.source_id, mention.target_id)
            row = rel_map.get(key)
            if row is None:
                attrs = _rel_attributes(mention)
                row = await self._relationships.create(
                    case_id=case_id,
                    rel_type=rel_type,
                    source_id=mention.source_id,
                    target_id=mention.target_id,
                    confidence=mention.confidence,
                    source_ids=[source_id],
                    attributes=attrs,
                )
                rel_map[key] = row
            else:
                row.confidence = max(row.confidence, mention.confidence)
                _merge_source_ids(row.source_ids, source_id)
                if mention.timestamp:
                    row.attributes = _merge_timestamps(row.attributes, mention.timestamp)
                await self._relationships.save(row)

        return entity_map, rel_map


def _merge_source_ids(source_ids: list, source_id: str) -> None:
    """Append a source id to a list in place when missing (dedupe)."""
    if source_id not in source_ids:
        source_ids.append(source_id)


def _rel_attributes(mention) -> dict:
    attrs: dict = {k: v for k, v in (mention.attributes or {}).items() if v not in (None, "")}
    if mention.timestamp:
        attrs["first_seen"] = mention.timestamp
        attrs["last_seen"] = mention.timestamp
        attrs["count"] = 1
        attrs["timestamps"] = [mention.timestamp]
    return attrs


def _merge_timestamps(attributes: dict, timestamp: str) -> dict:
    first = attributes.get("first_seen") or timestamp
    last = attributes.get("last_seen") or timestamp
    count = int(attributes.get("count") or 0) + 1
    timestamps = attributes.get("timestamps") or []
    if timestamp not in timestamps and len(timestamps) < 500:
        timestamps = [*timestamps, timestamp]
    return {
        **attributes,
        "first_seen": min(first, timestamp),
        "last_seen": max(last, timestamp),
        "count": count,
        "timestamps": timestamps,
    }


def _sanitize_filename(filename: str) -> str:
    base = os.path.basename(filename or "").strip()
    base = base.replace("\x00", "").replace("/", "_").replace("\\", "_")
    if len(base) > 255:
        _, ext = os.path.splitext(base)
        base = base[:255 - len(ext)] + ext
    return base or "unnamed"


def _slugify(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    slug = re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-")[:24].upper()
    return slug or "UPLOAD"
