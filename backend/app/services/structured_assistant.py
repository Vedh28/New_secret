"""Structured intelligence assistant (Task 5-6).

Routes a natural-language investigation question to a response TYPE and builds
a STRUCTURED intelligence object (key findings, entities, relationships,
anomalies, evidence, gaps, next-best-action) from the case intelligence
engines — never a flat text paragraph. Keeps a readable `summary` for display.
"""
from __future__ import annotations

import re

from app.intelligence.models import CaseData
from app.intelligence.offline import build_demo_case
from app.schemas.assistant import (
    AssistantEntity,
    AssistantRecommendation,
    AssistantRelItem,
    IntelligenceResponse,
    KeyFinding,
)

_ENTITY_RE = re.compile(r"([povaln]\-\d{3,})", re.IGNORECASE)


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


class StructuredAssistant:
    """Evidence-grounded, type-aware question answering."""

    def __init__(self, session, store, case_intel: dict | None = None) -> None:
        self._session = session
        self._store = store
        self._case_intel = case_intel  # optional dict from CaseIntelligenceService
        self._case_key: str | None = None

    async def answer(self, question: str, case_key: str | None = None) -> IntelligenceResponse:
        self._case_key = case_key
        q = question
        intent = _intent(q.lower())
        data = await self._load_case_data()
        return self._build(question, intent, data)

    async def _load_case_data(self) -> CaseData:
        """Load persisted case data when a case_key is provided.

        Falls back to the deterministic offline demo case when:
        - no case_key is given
        - the case cannot be resolved from the database
        - the session is unavailable
        """
        if self._case_key:
            try:
                from app.repositories.case_analytics_repo import build_case_data
                from app.repositories.case_repository import CaseRepository

                repo = CaseRepository(self._session)
                case = await repo.get_by_case_number(self._case_key)
                if case is None and self._case_key.isdigit():
                    case = await repo.get(int(self._case_key))
                if case is not None:
                    return await build_case_data(self._session, case.id)
            except Exception:  # noqa: BLE001 - graceful fallback when DB is unavailable
                pass
        return build_demo_case()

    def _build(self, question: str, intent: str, data: CaseData) -> IntelligenceResponse:
        match = _ENTITY_RE.search(question)
        entity_id = match.group(1).upper() if match else None
        entity = data.entity(entity_id) if entity_id else None

        if entity_id is not None and entity is None:
            # The referenced entity is not present in the selected case's data.
            return IntelligenceResponse(
                type="ENTITY_QUERY",
                query=question,
                summary=f"No supporting evidence found in the selected case for {entity_id}. "
                        "The case may not contain a record naming it.",
                found=False,
            )
        if entity is not None and intent in ("ENTITY_QUERY", "RELATIONSHIP_QUERY"):
            return self._entity_response(question, entity, data)
        if intent == "POTENTIAL_LINK_QUERY":
            return self._potential_response(question, data)
        if intent == "ANOMALY_QUERY":
            return self._anomaly_response(question, data)
        if intent == "RECOMMENDATION_QUERY" or intent == "CASE_QUERY":
            return self._case_response(question, data)
        return self._case_response(question, data)

    def _entity_response(self, question: str, entity, data: CaseData) -> IntelligenceResponse:
        neighbors = data.neighbors(entity.id)
        rels = [r for r in data.relationships if r.source == entity.id or r.target == entity.id]
        response = IntelligenceResponse(
            type="ENTITY_QUERY",
            query=question,
            summary=f"{entity.id} ({entity.name}) is a '{entity.type}' entity with "
                    f"{len(neighbors)} direct connection(s) and {len(rels)} recorded relationship(s).",
            key_findings=[
                KeyFinding(label="Entity type", detail=entity.type),
                KeyFinding(label="Direct connections", detail=str(len(neighbors))),
                KeyFinding(label="Relationship count", detail=str(len(rels))),
                KeyFinding(label="Aliases", detail=", ".join(entity.aliases) if entity.aliases else "—"),
            ],
            entities=[AssistantEntity(id=entity.id, type=entity.type, name=entity.name)],
            relationships=[
                AssistantRelItem(source=r.source, target=r.target, kind="CONFIRMED", confidence=r.confidence)
                for r in rels[:8]
            ] + self._potential_links(entity.id, data),
            evidence=[f"{e.source_id} ({e.source_type}) — {e.summary[:80]}" for e in data.evidence
                      if entity.id in e.entity_ids][:6],
            source_ids=[e.source_id for e in data.evidence if entity.id in e.entity_ids][:8],
            found=True,
        )
        return response

    def _potential_response(self, question: str, data: CaseData) -> IntelligenceResponse:
        from app.intelligence.potential_links import discover
        links = discover(data, top_k=5)
        return IntelligenceResponse(
            type="POTENTIAL_LINK_QUERY",
            query=question,
            summary=f"{len(links)} potential relationship(s) identified (not directly observed).",
            key_findings=[KeyFinding(label=f"{l.source}-{l.target}", detail=f"{l.score:.0f}% — {', '.join(l.supporting_signals[:2])}")
                          for l in links[:5]] if links else [],
            relationships=[
                AssistantRelItem(source=l.source, target=l.target, kind="POTENTIAL", confidence=l.confidence)
                for l in links[:5]
            ],
            evidence_gaps=[f"No direct communication evidence for {l.source}-{l.target}" for l in links[:5]],
            found=bool(links),
        )

    def _anomaly_response(self, question: str, data: CaseData) -> IntelligenceResponse:
        from app.intelligence.anomaly import detect_all
        from app.intelligence.offline import location_observations
        ans = detect_all(data, location_observations())
        return IntelligenceResponse(
            type="ANOMALY_QUERY",
            query=question,
            summary=f"{len(ans)} unusual investigative signal(s) detected.",
            anomalies=[f"{a.kind} {a.entity_id} — {a.explanation}" for a in ans[:6]],
            found=bool(ans),
        )

    def _case_response(self, question: str, data: CaseData) -> IntelligenceResponse:
        from app.intelligence import anomaly, dna, gaps, potential_links
        from app.intelligence.offline import location_observations
        import networkx as nx

        graph = nx.Graph()
        for e in data.entities:
            graph.add_node(e.id, type=e.type)
        for r in data.relationships:
            graph.add_edge(r.source, r.target, type=r.rel_type)

        links = potential_links.discover(data, top_k=3)
        gaps_list = gaps.gaps_for_potential_links(data, links)
        gene = dna.compute_dna(graph, data)
        ans = anomaly.detect_all(data, location_observations())

        nba = None
        if links:
            top = links[0]
            nba = AssistantRecommendation(
                kind="RELATIONSHIP",
                subject=f"{top.source}<->{top.target}",
                priority=top.score,
                info_gain=min(100.0, top.score),
                reasoning=top.supporting_signals[:3],
                recommended_data="CDR and location records between the pair",
                window="review the potential relationship",
            )

        return IntelligenceResponse(
            type="CASE_QUERY",
            query=question,
            summary=f"Case intelligence: {len(data.entities)} entities, {len(data.relationships)} relationships, "
                    f"{gene.community_count} communities, bridge dependence {gene.bridge_dependence}, "
                    f"{len(ans)} anomalies, {len(links)} potential links, {len(gaps_list)} evidence gaps.",
            key_findings=[
                KeyFinding(label="Network DNA — density", detail=f"{gene.density:.2f}"),
                KeyFinding(label="Bridge dependence", detail=gene.bridge_dependence),
                KeyFinding(label="Communities", detail=str(gene.community_count)),
                KeyFinding(label="Evidence coverage", detail=f"{gene.evidence_coverage}%"),
            ],
            entities=[AssistantEntity(id=e.id, type=e.type, name=e.name) for e in data.entities][:10],
            anomalies=[f"{a.kind} {a.entity_id}" for a in ans[:5]],
            evidence_gaps=[g.subject for g in gaps_list[:5]],
            next_best_action=nba,
            source_ids=list({e.source_id for e in data.evidence}),
            found=True,
        )

    def _potential_links(self, entity_id: str, data: CaseData) -> list[AssistantRelItem]:
        from app.intelligence.potential_links import discover
        links = discover(data, top_k=8)
        return [
            AssistantRelItem(source=l.source, target=l.target, kind="POTENTIAL", confidence=l.confidence)
            for l in links if entity_id in (l.source, l.target)
        ]