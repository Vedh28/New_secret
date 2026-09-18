"""Report endpoints (P0.2, hardened).

Reports persist in PostgreSQL; integrity registration + verification use the
same canonical hash as the persisted record.
"""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.blockchain.hashes import hash_report_payload, report_integrity_payload
from app.repositories.case_repository import CaseRepository
from app.reports.service import ReportService
from app.schemas.report import ReportMeta, ReportRequest, ReportResponse

router = APIRouter()


async def _resolve_case_id(session, case_key: str | None) -> int | None:
    if not case_key:
        return None
    repo = CaseRepository(session)
    case = await repo.get_by_case_number(case_key)
    if case is not None:
        return case.id
    if str(case_key).isdigit():
        case = await repo.get(int(case_key))
        if case is not None:
            return case.id
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


@router.post(
    "/generate",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a report from live application state",
)
async def generate_report(
    payload: ReportRequest,
    session: DbSession,
    store: GraphStoreDep,
    user: CurrentUser,
) -> ReportResponse:
    report = await ReportService(session, store, user).generate(payload)
    case_id = (await _resolve_case_id(session, payload.case_number)) if payload.case_number else None
    integrity = None
    if case_id is not None:
        current_hash = hash_report_payload(report_integrity_payload(
            report_id=report.id, report_type=report.report_type, title=report.title,
            sections=[{"heading": s.heading, "body": s.body} for s in report.sections],
            generated_at=str(report.generated_at),
        ))
        try:
            from app.blockchain.service import BlockchainIntegrityService
            integrity = await BlockchainIntegrityService(session).register_report(
                case_id=case_id, report=report, actor_id=user.id, report_hash=current_hash,
            )
        except Exception:  # noqa: BLE001 - integrity failure must not break reporting
            integrity = None
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            user, "report_generated", object_type="report", object_id=report.id,
            result={"report_type": report.report_type,
                    "case_number": payload.case_number or "",
                    "integrity_tx": (integrity or {}).get("transaction_id") or "",
                    "report_hash": (integrity or {}).get("report_hash") or current_hash if case_id else ""},
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        pass
    return report


@router.get(
    "",
    response_model=list[ReportMeta],
    summary="List generated reports (optionally for one case)",
)
async def list_reports(
    session: DbSession,
    _user: CurrentUser,
    case_number: Annotated[str | None, Query(description="Scope the listing to one case")] = None,
) -> list[ReportMeta]:
    return await ReportService(session, None, None).list_meta(case_number=case_number)


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Get a previously generated report (persisted)",
)
async def get_report(
    report_id: str,
    session: DbSession,
    _user: CurrentUser,
    case_number: Annotated[str | None, Query(description="Require the report to belong to this case")] = None,
) -> ReportResponse:
    report = await _load_report(session, report_id, case_number)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


async def _load_report(session, report_id: str, case_number: str | None):
    """Case-scoped report load. When case_number provided, ownership is enforced."""
    from app.repositories.report_repository import ReportRepository

    repo = ReportRepository(session)
    row = await repo.get(report_id)
    if row is None:
        return None
    if case_number:
        case_id = await _resolve_case_id(session, case_number)
        if case_id is None or row.case_id != case_id:
            return None
    from app.reports.service import _row_to_response
    return _row_to_response(row)