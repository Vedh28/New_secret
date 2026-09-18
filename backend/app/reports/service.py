"""Report service (P0.2, hardened).

Reports are now persisted in PostgreSQL so they survive process restarts and
integrity verification continues to work across reboots. The service builds the
report, stores it, computes a canonical report hash (same algorithm used for
integrity registration) and returns the full API response including the hash.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.hashes import hash_report_payload, report_integrity_payload
from app.models.report import Report
from app.models.user import User
from app.reports.builders import BUILDERS
from app.reports.pdf import encode_pdf_artifact
from app.repositories.report_repository import ReportRepository
from app.schemas.report import ReportMeta, ReportRequest, ReportResponse, ReportSection


def _lines(sections: list[ReportSection]) -> list[str]:
    out: list[str] = []
    for section in sections:
        out.append("")
        out.append(f"## {section.heading}")
        out.extend(section.body)
    return out


class ReportService:
    """Generate and retrieve reports (persisted in PostgreSQL)."""

    def __init__(self, session: AsyncSession, store, user: User) -> None:
        self._session = session
        self._store = store  # graph store (used by builders)
        self._user = user

    async def generate(self, request: ReportRequest) -> ReportResponse:
        builder = BUILDERS[request.report_type]

        if request.report_type == "investigation_summary":
            sections = await builder(self._session, self._store, request.case_number or "", request.title or "")
        elif request.report_type == "entity_intelligence":
            sections = await builder(self._session, self._store, request.entity_id or "", request.title or "")
        else:
            sections = await builder(self._session, self._store, request.title or "")

        title = request.title or request.report_type.replace("_", " ").title()
        artifact = encode_pdf_artifact(_lines(sections), title)
        report_id = uuid.uuid4().hex
        generated_at = datetime.now(timezone.utc)

        # Canonical sections for hashing: consistent dict shape whether
        # originating from pydantic objects or loaded back from JSON.
        canonical_sections = [{"heading": s.heading, "body": list(s.body)} for s in sections]

        # Canonical hash (same logic used at registration + verification).
        report_hash = hash_report_payload(report_integrity_payload(
            report_id=report_id, report_type=request.report_type,
            title=title, sections=canonical_sections,
            generated_at=generated_at.isoformat(),
        ))

        # Resolve optional case id for the foreign key.
        case_id = None
        if request.case_number:
            from app.repositories.case_repository import CaseRepository
            repo = CaseRepository(self._session)
            case = await repo.get_by_case_number(request.case_number)
            if case is None and request.case_number.isdigit():
                case = await repo.get(int(request.case_number))
            if case is not None:
                case_id = case.id

        persisted = await ReportRepository(self._session).create(
            id=report_id,
            case_id=case_id,
            report_type=request.report_type,
            title=title,
            generated_by=self._user.username,
            sections_json=canonical_sections,
            artifact=artifact,
            artifact_mime="application/pdf",
            report_hash=report_hash,
            generated_at=generated_at,
        )

        return ReportResponse(
            id=persisted.id,
            report_type=persisted.report_type,
            title=persisted.title,
            generated_at=persisted.generated_at,
            generated_by=persisted.generated_by,
            sections=sections,
            artifact=persisted.artifact,
        )

    async def get(self, report_id: str) -> ReportResponse | None:
        row = await ReportRepository(self._session).get(report_id)
        if row is None:
            return None
        return _row_to_response(row)

    async def list_meta(self, case_number: str | None = None) -> list[ReportMeta]:
        repo = ReportRepository(self._session)
        if case_number:
            from app.repositories.case_repository import CaseRepository
            case = await CaseRepository(self._session).get_by_case_number(case_number)
            if case is None and case_number.isdigit():
                case = await (CaseRepository(self._session)).get(int(case_number))
            if case is None:
                return []
            rows = await repo.list_by_case(case.id)
        else:
            rows = await repo.list_recent()
        return [
            ReportMeta(
                id=r.id, report_type=r.report_type, title=r.title,
                generated_at=r.generated_at, generated_by=r.generated_by,
                sections=len(r.sections_json),
            )
            for r in rows
        ]


def _row_to_response(row: Report) -> ReportResponse:
    return ReportResponse(
        id=row.id,
        report_type=row.report_type,
        title=row.title,
        generated_at=row.generated_at,
        generated_by=row.generated_by,
        sections=[ReportSection(heading=s.get("heading", ""), body=s.get("body", [])) for s in row.sections_json],
        artifact=row.artifact,
    )