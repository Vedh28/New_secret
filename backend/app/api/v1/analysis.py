"""Temporal/location + investigation workflow endpoints (Phases 9-10)."""
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, GraphStoreDep, RequireAnalyst
from app.ingestion.generator import generate_synthetic
from app.schemas.analysis import TemporalLocationResponse
from app.schemas.assistant import AssistantRequest, AssistantResponse
from app.schemas.assistant import AssistantRecommendation, KeyFinding
from app.services.analysis_service import TemporalLocationService
from app.services.structured_assistant import StructuredAssistant
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
    structured = await StructuredAssistant(session, store).answer(payload.question, case_key=payload.case_key)
    if payload.case_key:
        # When a case is requested, pull live case intelligence to enrich the answer.
        try:
            from app.services.case_intelligence_service import CaseIntelligenceService
            from app.repositories.case_repository import CaseRepository
            repo = CaseRepository(session)
            case = await repo.get_by_case_number(payload.case_key) or (
                await repo.get(int(payload.case_key)) if payload.case_key.isdigit() else None
            )
            if case is not None:
                intel = await CaseIntelligenceService(session).build(case.id)
                structured = await _enrich(structured, intel)
        except Exception:  # noqa: BLE001 - keep offline fallback on any failure
            pass
    return AssistantResponse(
        question=payload.question,
        answer=structured.summary,
        source_ids=structured.source_ids,
        found=structured.found,
        structured=structured,
    )


async def _enrich(structured, intel: dict):
    """Fold real case-intelligence numbers into the structured response."""
    if intel.get("network_dna"):
        structured.key_findings.insert(0, KeyFinding(
            label="Live network DNA",
            detail=f"{intel['network_dna'].density:.2f} density",
        ))
    if intel.get("recommendations"):
        top = intel["recommendations"][0]
        structured.next_best_action = AssistantRecommendation(
            kind=top.get("kind", ""), subject=top.get("subject", ""),
            priority=top.get("priority", 0.0), info_gain=top.get("info_gain", 0.0),
            reasoning=top.get("reasoning", []), recommended_data=top.get("recommended_data", ""),
            window=top.get("window", ""),
        )
    return structured


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
