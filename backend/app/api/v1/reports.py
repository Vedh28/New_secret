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
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            user, "report_generated", object_type="report", object_id=report.id,
            result={"report_type": report.report_type,
                    "case_number": getattr(payload, "case_number", None) or ""},
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
