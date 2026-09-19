"""Temporal/location + investigation workflow endpoints (Phases 9-10)."""
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.ingestion.generator import generate_synthetic
from app.schemas.analysis import TemporalLocationResponse
from app.schemas.assistant import AssistantRequest, AssistantResponse, IntelligenceResponse
from app.services.analysis_service import TemporalLocationService
from app.services.investigation_engine import InvestigationEngine
from app.services.simulation_service import SimulationService

router = APIRouter()


@router.get(
    "/temporal-location",
    response_model=TemporalLocationResponse,
    summary="Temporal + location correlation over source records",
)
async def temporal_location(
    _user: CurrentUser,
    scenario: Annotated[str, Query(description="Synthetic data scenario")] = "NORMAL_NETWORK",
    entity_id: Annotated[str | None, Query(description="Filter events to one entity")] = None,
) -> TemporalLocationResponse:
    service = TemporalLocationService()
    events = generate_synthetic(scenario)
    return service.analyze(events, scenario=scenario, entity_id=entity_id)


@router.post(
    "/investigation",
    summary="Run the full investigation workflow over a scenario",
)
async def run_investigation(
    store: GraphStoreDep,
    session: DbSession,
    _: RequireAnalyst,
    scenario: Annotated[str, Query()] = "NORMAL_NETWORK",
) -> dict:
    """Execute generate -> ingest -> extract -> resolve -> graph -> analyze."""
    summary = await InvestigationEngine(store).run(scenario=scenario)
    await session.commit()
    return summary


@router.post(
    "/assistant",
    response_model=AssistantResponse,
    summary="Ask the local dataset analyst a question (evidence-grounded, structured)",
)
async def assistant(
    payload: AssistantRequest,
    store: GraphStoreDep,
    session: DbSession,
    _user: CurrentUser,
) -> AssistantResponse:
    from fastapi import HTTPException, status as http_status

    from app.repositories.case_repository import CaseRepository

    # Live assistant REQUIRES a case. Explicitly resolve it first.
    repo = CaseRepository(session)
    case = None
    if payload.case_key:
        case = await repo.get_by_case_number(payload.case_key)
        if case is None and payload.case_key.isdigit():
            case = await repo.get(int(payload.case_key))

    if case is None:
        # CASE DOES NOT EXIST -> explicit response, never demo data.
        not_found = IntelligenceResponse(
            type="CASE_QUERY",
            query=payload.question,
            summary=(f"Case not found: {payload.case_key or 'none supplied'}. "
                     "The assistant can only answer for a case that exists."),
            found=False,
        )
        return AssistantResponse(
            question=payload.question,
            answer=not_found.summary,
            source_ids=[],
            found=False,
            structured=not_found,
        )

    try:
        from app.services.case_intelligence_service import CaseIntelligenceService
        intel = await CaseIntelligenceService(session).build(case.id)
    except Exception as exc:  # noqa: BLE001 - backend failure must surface, not become demo
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intelligence backend unavailable for this case; no data was returned.",
        ) from exc

    from app.services.structured_assistant import StructuredAssistant, case_data_from_intel
    integrity = None
    try:
        from app.blockchain.service import BlockchainIntegrityService
        integrity = await BlockchainIntegrityService(session).case_summary(case.id)
    except Exception:  # noqa: BLE001 - assistant still answers without integrity context
        integrity = None
    structured = await StructuredAssistant(session, store).answer(
        payload.question, case_key=payload.case_key,
        intel=intel, case_data=case_data_from_intel(intel), integrity=integrity,
    )
    try:
        from app.services.audit_service import AuditService
        await AuditService(session).record(
            _user, "assistant_query", object_type="case", object_id=payload.case_key,
            result={"intent": structured.type, "found": structured.found},
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - best-effort audit
        import logging
        logging.getLogger("secret.audit").warning(
            "assistant query audit failed case=%s type=%s",
            payload.case_key, type(exc).__name__)
    return AssistantResponse(
        question=payload.question,
        answer=structured.summary,
        source_ids=structured.source_ids,
        found=structured.found,
        structured=structured,
    )


@router.post(
    "/simulation",
    summary="Run the full intelligence simulation pipeline",
)
async def run_simulation(
    store: GraphStoreDep,
    _user: CurrentUser,
    scenario: Annotated[str, Query()] = "NORMAL_NETWORK",
) -> dict:
    return await SimulationService(store).run(scenario=scenario)
