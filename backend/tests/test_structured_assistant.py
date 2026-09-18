"""Structured assistant response tests (Task 5-6)."""
import asyncio

import pytest

from app.services.structured_assistant import StructuredAssistant, _intent


def test_intent_routing() -> None:
    assert _intent("show connections of P-0421") == "RELATIONSHIP_QUERY"
    assert _intent("what is P-0312") == "ENTITY_QUERY"
    assert _intent("unusual activity bursts") == "ANOMALY_QUERY"
    assert _intent("potential hidden links") == "POTENTIAL_LINK_QUERY"
    assert _intent("where in sector 17") == "LOCATION_QUERY"
    assert _intent("evidence for this") == "EVIDENCE_QUERY"
    assert _intent("recommend next") == "RECOMMENDATION_QUERY"
    assert _intent("case overview") == "CASE_QUERY"


def _run(q: str, **kwargs):
    sa = StructuredAssistant(None, None)

    async def go():
        return await sa.answer(q, **kwargs)

    return asyncio.run(go())


def test_offline_mode_uses_demo_snapshot() -> None:
    res = _run("show connections of P-0421", offline=True)
    assert res.found is True
    assert any(e.id == "P-0421" for e in res.entities)


def test_live_without_snapshot_raises_not_demo() -> None:
    # A live call without a loaded snapshot must FAIL loudly, never return demo.
    import pytest

    from app.services.structured_assistant import AssistantDataUnavailable

    with pytest.raises(AssistantDataUnavailable):
        _run("how is the case going?")


def test_entity_query_structured() -> None:
    res = _run("show connections of P-0421", offline=True)
    assert res.type == "ENTITY_QUERY"
    assert res.found is True
    assert res.summary
    assert any(e.id == "P-0421" for e in res.entities)
    assert res.relationships  # confirmed neighbors
    # P-0421<->P-0312 is a potential link, not confirmed.
    potential = [r for r in res.relationships if r.kind == "POTENTIAL"]
    assert any({r.source, r.target} == {"P-0421", "P-0312"} for r in potential)


def test_case_query_has_dna_and_next_action() -> None:
    res = _run("what should I investigate next", offline=True)
    assert res.type in ("RECOMMENDATION_QUERY", "CASE_QUERY")
    assert any(k.label == "Network DNA — density" for k in res.key_findings)
    assert res.next_best_action is not None
    assert res.next_best_action.recommended_data


def test_anomaly_query() -> None:
    res = _run("unusual bursts", offline=True)
    assert res.type == "ANOMALY_QUERY"
    assert res.anomalies


def test_potential_link_query() -> None:
    res = _run("potential hidden links", offline=True)
    assert res.type == "POTENTIAL_LINK_QUERY"
    assert any(r.kind == "POTENTIAL" for r in res.relationships)
    assert res.evidence_gaps