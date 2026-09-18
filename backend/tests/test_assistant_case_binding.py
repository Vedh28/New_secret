"""P0-1: assistant must answer against the SELECTED case — never silently
fall back to demo data during a live request."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.case import Case, CasePriority, CaseStatus
from app.models.entity import Entity, EntityRelationship
from app.models.source import Source
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.structured_assistant import AssistantDataUnavailable, StructuredAssistant, case_data_from_intel


async def _seed(S) -> dict:
    case = Case(case_number="CASE-TEST-0007", title="Selected Case Test",
                status=CaseStatus.OPEN.value, priority=CasePriority.CRITICAL.value)
    async with S() as session:
        session.add(case)
        await session.flush()
        session.add_all([
            Entity(case_id=case.id, entity_id="P-9901", entity_type="PERSON",
                   name="Selected Person Alpha", confidence=0.9, source_ids=["SELECTED-001"]),
            Entity(case_id=case.id, entity_id="P-9902", entity_type="PERSON",
                   name="Selected Person Beta", confidence=0.9, source_ids=["SELECTED-001"]),
            EntityRelationship(case_id=case.id, rel_type="CALLED", source_id="P-9901",
                               target_id="P-9902", confidence=0.8, source_ids=["SELECTED-001"],
                               attributes={"first_seen": "2026-09-01T10:00",
                                           "last_seen": "2026-09-01T10:00", "count": 1}),
            Source(case_id=case.id, source_id="SELECTED-001", filename="selected.txt",
                   file_type="TEXT", source_type="FIR", status="PROCESSED",
                   record_count=1, processed_at=None,
                   metadata_json={"records": [
                       {"id": "r1", "timestamp": "2026-09-01T10:00", "text": "Selected case source text",
                        "fields": {"caller_phone": "P-9901", "receiver_phone": "P-9902"}},
                   ], "text": "Selected case source text"}),
        ])
        await session.commit()
    return {"case_key": "CASE-TEST-0007", "case_id": case.id}


@pytest.fixture()
async def case_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ctx = await _seed(S)
    yield ctx, S
    await engine.dispose()


async def test_assistant_binds_to_selected_case(case_ctx) -> None:
    ctx, S = case_ctx
    async with S() as session:
        intel = await CaseIntelligenceService(session).build(ctx["case_id"])
        sa = StructuredAssistant(session, None)
        res = await sa.answer(
            "show connections of P-9901", case_key=ctx["case_key"],
            intel=intel, case_data=case_data_from_intel(intel),
        )

    # The answer must reference the SELECTED case's entities, not the demo corpus.
    assert res.found is True
    assert any(e.id == "P-9901" and e.name == "Selected Person Alpha" for e in res.entities)
    assert "P-9902" in {r.target for r in res.relationships if r.source == "P-9901"}
    assert res.evidence and any("SELECTED-001" in s for s in res.evidence)
    assert "P-0421" not in {e.id for e in res.entities}  # demo entity must be absent


async def test_assistant_without_snapshot_raises(case_ctx) -> None:
    """A live call with no snapshot must fail loudly instead of demo data."""
    ctx, S = case_ctx
    async with S() as session:
        sa = StructuredAssistant(session, None)
        with pytest.raises(AssistantDataUnavailable):
            await sa.answer("what should I investigate next", case_key=ctx["case_key"])


async def test_assistant_explicit_offline_flag_uses_demo(case_ctx) -> None:
    """build_demo_case() is ONLY reachable through the explicit offline path."""
    _, S = case_ctx
    async with S() as session:
        sa = StructuredAssistant(session, None)
        res = await sa.answer("show connections of P-0421", offline=True)
    assert res.found is True
    assert any(e.id == "P-0421" for e in res.entities)


async def test_assistant_entity_not_in_case(case_ctx) -> None:
    """An entity the selected case does not contain yields a clear not-found."""
    ctx, S = case_ctx
    async with S() as session:
        intel = await CaseIntelligenceService(session).build(ctx["case_id"])
        sa = StructuredAssistant(session, None)
        res = await sa.answer(
            "who is P-9999", case_key=ctx["case_key"],
            intel=intel, case_data=case_data_from_intel(intel),
        )
    assert res.found is False
    assert "P-9999" in res.summary
    assert res.entities == []