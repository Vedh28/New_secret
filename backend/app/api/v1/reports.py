"""Report endpoints (Phase 9)."""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.reports.service import ReportService, _STORE
from app.schemas.report import ReportMeta, ReportRequest, ReportResponse

router = APIRouter()


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
    case_key = getattr(payload, "case_number", None)
    case_id = None
    if case_key:
        from app.repositories.case_repository import CaseRepository
        case = await CaseRepository(session).get_by_case_number(case_key) or (
            await CaseRepository(session).get(int(case_key)) if str(case_key).isdigit() else None
        )
        case_id = case.id if case else None
    integrity = None
    if case_id is not None:
        try:
            from app.blockchain.service import BlockchainIntegrityService
            integrity = await BlockchainIntegrityService(session).register_report(
                case_id=case_id, report=report, actor_id=user.id,
            )
        except Exception:  # noqa: BLE001 - integrity failure must not break reporting
            integrity = None
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            user, "report_generated", object_type="report", object_id=report.id,
            result={"report_type": report.report_type,
                    "case_number": case_key or "",
                    "integrity_tx": (integrity or {}).get("transaction_id") or "",
                    "report_hash": (integrity or {}).get("report_hash") or ""},
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        pass
    return report


@router.get(
    "",
    response_model=list[ReportMeta],
    summary="List generated reports",
)
async def list_reports(
    _user: CurrentUser,
) -> list[ReportMeta]:
    service = ReportService(None, None, None)
    return service.list_meta()


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Get a previously generated report",
)
async def get_report(
    report_id: str,
    _user: CurrentUser,
) -> ReportResponse:
    report = _STORE.get(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report
