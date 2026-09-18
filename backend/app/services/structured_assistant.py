"""Structured intelligence assistant (Task 5-6, hardened).

The assistant is a THIN PRESENTATION layer over the canonical case
intelligence snapshot produced by CaseIntelligenceService. It never recalculates
anomalies / DNA / potential links / gaps itself and never ingests offline demo
maps for a live case.

Behavior contract (P0-1):

    LIVE CASE FOUND      -> answers from the persisted case snapshot
    CASE DOES NOT EXIST  -> explicit "case not found" response (found=False)
    BACKEND FAILURE      -> AssistantDataUnavailable raised (never demo data)
    OFFLINE DEMO MODE    -> explicitly built synthetic snapshot
"""
from __future__ import annotations

import re

from app.intelligence.models import CaseData
from app.schemas.assistant import (
    AssistantEntity,
    AssistantRecommendation,
    AssistantRelItem,
    IntelligenceResponse,
    KeyFinding,
)

_ENTITY_RE = re.compile(r"([povaln]\-\d{3,})", re.IGNORECASE)


class AssistantDataUnavailable(RuntimeError):
    """The assistant cannot answer because required case data is unavailable.

    Raised on backend/data availability failures — the caller decides the HTTP
    response. It is deliberately NOT swallowed into demo data.
    """


def _intent(q: str) -> str:
    if _ENTITY_RE.search(q) and any(k in q for k in ("connection", "relationship", "neighbor", "link")):
        return "RELATIONSHIP_QUERY"
    if _ENTITY_RE.search(q):
        return "ENTITY_QUERY"
    if any(k in q for k in ("anomal", "unusual", "burst")):
        return "ANOMALY_QUERY"
    if any(k in q for k in ("potential", "hidden")):
        return "POTENTIAL_LINK_QUERY"
    if any(k in q for k in ("location", "sector", "dock")):
        return "LOCATION_QUERY"
    if any(k in q for k in ("time", "timeline", "when")):
        return "TIMELINE_QUERY"
    if any(k in q for k in ("evidence", "source")):
        return "EVIDENCE_QUERY"
    if any(k in q for k in ("recommend", "next", "act")):
        return "RECOMMENDATION_QUERY"
    if any(k in q for k in ("case", "overview", "investigation")):
        return "CASE_QUERY"
    return "GENERAL_INVESTIGATION_QUERY"


def case_data_from_intel(intel: dict) -> CaseData:
    """Reconstruct the engine's CaseData from a canonical intelligence snapshot."""
    return CaseData(
        case_number="",
        entities=list(intel.get("entities", [])),
        relationships=list(intel.get("relationships", [])),
        evidence=list(intel.get("evidence", [])),
    )


def offline_intelligence_snapshot() -> tuple[CaseData, dict]:
    """Explicit offline/demo snapshot using the same engine as live mode."""
    from app.intelligence.offline import build_demo_case
    from app.services.case_intelligence_service import compute_from_data

    data = build_demo_case()
    return data, compute_from_data(case_id=-1, data=data, link_decisions={})


class StructuredAssistant:
    """Evidence-grounded, type-aware question answering over one case snapshot."""

    def __init__(self, session, store, case_intel: dict | None = None) -> None:
        self._session = session
        self._store = store
        self._case_key: str | None = None

    async def answer(
        self,
        question: str,
        case_key: str | None = None,
        intel: dict | None = None,
        case_data: CaseData | None = None,
        offline: bool = False,
    ) -> IntelligenceResponse:
        """Answer from ONE explicit source: live snapshot or offline demo.

        Live mode never touches demo data. Demo mode is only reached when
        `offline=True` is passed explicitly.
        """
        self._case_key = case_key
        intent = _intent(question.lower())

        if offline:
            self._data, self._intel = offline_intelligence_snapshot()
        elif intel is not None and case_data is not None:
            self._intel = intel
            self._data = case_data
        else:
            raise AssistantDataUnavailable(
                "Live assistant requires a loaded case intelligence snapshot; none was provided."
            )

        return self._build(question, intent)

    def _build(self, question: str, intent: str) -> IntelligenceResponse:
        match = _ENTITY_RE.search(question)
        entity_id = match.group(1).upper() if match else None
        entity = self._data.entity(entity_id) if entity_id else None

        if entity_id is not None and entity is None:
            return self._not_found(question, entity_id)
        if entity is not None and intent in ("ENTITY_QUERY", "RELATIONSHIP_QUERY"):
            return self._entity_response(question, entity)
        if intent == "POTENTIAL_LINK_QUERY":
            return self._potential_response(question)
        if intent == "ANOMALY_QUERY":
            return self._anomaly_response(question)
        if intent == "LOCATION_QUERY":
            return self._location_response(question)
        if intent == "TIMELINE_QUERY":
            return self._timeline_response(question)
        if intent == "EVIDENCE_QUERY":
            return self._evidence_response(question)
        if intent == "RECOMMENDATION_QUERY" or intent == "CASE_QUERY":
            return self._case_response(question)
        return self._case_response(question)

    def _not_found(self, question: str, entity_id: str) -> IntelligenceResponse:
        return IntelligenceResponse(
            type="ENTITY_QUERY",
            query=question,
            summary=f"No supporting evidence found in the selected case for {entity_id}. "
                    "The case may not contain a record naming it.",
            found=False,
        )

    def _entity_response(self, question: str, entity) -> IntelligenceResponse:
        data = self._data
        neighbors = data.neighbors(entity.id)
        rels = [r for r in data.relationships if r.source == entity.id or r.target == entity.id]
        related_evidence = [e for e in data.evidence if entity.id in e.entity_ids]
        return IntelligenceResponse(
            type="ENTITY_QUERY",
            query=question,
            summary=f"{entity.id} ({entity.name}) is a '{entity.type}' entity with "
                    f"{len(neighbors)} direct connection(s), {len(rels)} recorded relationship(s) "
                    f"and {len(related_evidence)} evidence reference(s).",
            key_findings=[
                KeyFinding(label="Entity type", detail=entity.type),
                KeyFinding(label="Direct connections", detail=str(len(neighbors))),
                KeyFinding(label="Relationship count", detail=str(len(rels))),
                KeyFinding(label="Evidence references", detail=str(len(related_evidence))),
            ],
            entities=[AssistantEntity(id=entity.id, type=entity.type, name=entity.name)],
            relationships=[
                AssistantRelItem(source=r.source, target=r.target, kind="CONFIRMED", confidence=r.confidence)
                for r in rels[:8]
            ] + self._potential_links(entity.id),
            evidence=[f"{e.source_id} ({e.source_type}) — {e.summary[:80]}" for e in related_evidence][:6],
            source_ids=[e.source_id for e in related_evidence][:8],
            found=True,
        )

    def _potential_response(self, question: str) -> IntelligenceResponse:
        links = [link for link in self._intel.get("potential_links", [])]
        return IntelligenceResponse(
            type="POTENTIAL_LINK_QUERY",
            query=question,
            summary=f"{len(links)} potential relationship(s) identified (not directly observed).",
            key_findings=[
                KeyFinding(label=f"{l['source']}-{l['target']}",
                           detail=f"{l.get('score', 0):.0f}% — {', '.join(l.get('supporting_signals', [])[:2])}")
                for l in links[:5]
            ] if links else [],
            relationships=[
                AssistantRelItem(source=l["source"], target=l["target"], kind="POTENTIAL",
                                 confidence=l.get("confidence", 0.0))
                for l in links[:5]
            ],
            evidence=[", ".join(l.get("evidence_ids", [])) for l in links[:5]
                      if l.get("evidence_ids")],
            evidence_gaps=[
                f"No direct communication evidence for {l['source']}-{l['target']}"
                for l in links[:5]
                if any("direct communication" in c for c in l.get("contradictory_signals", []))
            ],
            source_ids=list({sid for l in links for sid in l.get("evidence_ids", [])}),
            found=bool(links),
        )

    def _anomaly_response(self, question: str) -> IntelligenceResponse:
        ans = self._intel.get("anomalies", [])
        return IntelligenceResponse(
            type="ANOMALY_QUERY",
            query=question,
            summary=f"{len(ans)} unusual investigative signal(s) detected for the selected case.",
            anomalies=[f"{a.get('kind')} {a.get('entity_id', '')} — {a.get('explanation', '')}"
                       for a in ans[:6]],
            source_ids=list({sid for a in ans for sid in a.get("evidence", [])}),
            found=bool(ans),
        )

    def _location_response(self, question: str) -> IntelligenceResponse:
        from app.intelligence.locations import case_location_observations

        observations = case_location_observations(self._data)
        locations = self._data
        top = sorted(observations.items(), key=lambda kv: -kv[1])[:8]
        return IntelligenceResponse(
            type="LOCATION_QUERY",
            query=question,
            summary=f"{len(observations)} location(s) with recorded observations in this case.",
            key_findings=[
                KeyFinding(label=name, detail=f"{count} observation{'s' if count != 1 else ''}")
                for name, count in top
            ],
            entities=[
                AssistantEntity(id=e.id, type=e.type, name=e.name)
                for e in locations.entities if e.type.upper() == "LOCATION"
            ][:10],
            found=bool(observations),
        )

    def _timeline_response(self, question: str) -> IntelligenceResponse:
        changes = self._intel.get("temporal_changes", [])
        emerging = [c for c in changes if c.get("kind") == "EMERGING_BRIDGE"]
        return IntelligenceResponse(
            type="TIMELINE_QUERY",
            query=question,
            summary=f"{len(changes)} temporal change(s) observed for this case, "
                    f"including {len(emerging)} emerging bridge signal(s).",
            key_findings=[
                KeyFinding(label=f"{c.get('kind')} {c.get('source', '')}",
                           detail=c.get("explanation", ""))
                for c in changes[:6]
            ],
            found=bool(changes),
        )

    def _evidence_response(self, question: str) -> IntelligenceResponse:
        evidence = self._data.evidence
        return IntelligenceResponse(
            type="EVIDENCE_QUERY",
            query=question,
            summary=f"{len(evidence)} evidence record(s) linked to this case.",
            evidence=[f"{e.source_id} ({e.source_type}) — {e.summary[:100]}" for e in evidence][:10],
            source_ids=list({e.source_id for e in evidence}),
            found=bool(evidence),
        )

    def _case_response(self, question: str) -> IntelligenceResponse:
        intel = self._intel
        dna = intel.get("network_dna", {})
        links = intel.get("potential_links", [])
        gaps = intel.get("evidence_gaps", [])
        ans = intel.get("anomalies", [])
        recommendations = intel.get("recommendations", [])
        decisions = intel.get("link_decisions", {})

        summary = (f"Case intelligence: {len(intel.get('entities', []))} entities, "
                   f"{len(intel.get('relationships', []))} relationships, "
                   f"{dna.get('community_count', 0)} communities, "
                   f"bridge dependence {dna.get('bridge_dependence', 'LOW')}, "
                   f"{len(ans)} anomalies, {len(links)} potential links, "
                   f"{len(gaps)} evidence gaps.")
        confirmed = [k for k, v in decisions.items() if v.get("new_status") == "ANALYST_CONFIRMED"]

        nba = None
        if recommendations:
            top = recommendations[0]
            nba = AssistantRecommendation(
                kind=top.get("kind", ""), subject=top.get("subject", ""),
                priority=top.get("priority", 0.0), info_gain=top.get("info_gain", 0.0),
                reasoning=top.get("reasoning", []), recommended_data=top.get("recommended_data", ""),
                window=top.get("window", ""),
            )

        return IntelligenceResponse(
            type="CASE_QUERY",
            query=question,
            summary=summary,
            key_findings=[
                KeyFinding(label="Network DNA — density", detail=f"{dna.get('density', 0):.2f}"),
                KeyFinding(label="Bridge dependence", detail=dna.get("bridge_dependence", "LOW")),
                KeyFinding(label="Communities", detail=str(dna.get("community_count", 0))),
                KeyFinding(label="Evidence coverage", detail=f"{dna.get('evidence_coverage', 0)}%"),
                KeyFinding(label="Analyst confirmed links", detail=str(len(confirmed))),
            ],
            entities=[
                AssistantEntity(id=e.id, type=e.type, name=e.name,
                                priority=_entity_priority(intel, e.id))
                for e in self._data.entities
            ][:10],
            anomalies=[f"{a.get('kind')} {a.get('entity_id', '')}" for a in ans[:5]],
            evidence_gaps=[g.get("subject", "") for g in gaps[:5]],
            next_best_action=nba,
            source_ids=list({e.source_id for e in self._data.evidence}),
            found=True,
        )

    def _potential_links(self, entity_id: str) -> list[AssistantRelItem]:
        return [
            AssistantRelItem(source=l["source"], target=l["target"], kind="POTENTIAL",
                             confidence=l.get("confidence", 0.0))
            for l in self._intel.get("potential_links", [])
            if entity_id in (l["source"], l["target"])
        ]


def _entity_priority(intel: dict, entity_id: str) -> float:
    for p in intel.get("entity_priorities", []):
        if p.get("subject") == entity_id:
            return float(p.get("priority", 0.0))
    return 0.0