"""Report builders (Phase 9).

Each builder assembles report sections from live application state: the
relational DB (cases, profiles) and graph analytics (NetworkX over the store).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case import Case, CaseCriminal
from app.models.criminal import CriminalProfile
from app.schemas.report import ReportSection
from app.services.analytics_service import AnalyticsService


async def _case(session: AsyncSession, case_number: str) -> Case | None:
    result = await session.execute(select(Case).where(Case.case_number == case_number))
    return result.scalar_one_or_none()


async def _case_profiles(session: AsyncSession, case_id: int) -> list[CriminalProfile]:
    stmt = (
        select(CriminalProfile)
        .join(CaseCriminal, CaseCriminal.profile_id == CriminalProfile.id)
        .where(CaseCriminal.case_id == case_id)
        .order_by(CriminalProfile.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _fmt_lines(mapping: dict) -> list[str]:
    return [f"{k}: {v}" for k, v in mapping.items()]


async def build_investigation_summary(
    session: AsyncSession,
    store,
    case_number: str,
    title: str,
) -> list[ReportSection]:
    case = await _case(session, case_number)
    if case is None:
        return [
            ReportSection(
                heading="Investigation Summary",
                body=[f"No case found for {case_number}.", "Report reflects no associated records."],
            )
        ]
    sections = await _investigation_summary_sections(session, store, case, title)
    sections.extend(await _case_intelligence_sections(session, case))
    return sections


async def _investigation_summary_sections(
    session: AsyncSession, store, case, title: str
) -> list[ReportSection]:
    sections: list[ReportSection] = []

    profiles = await _case_profiles(session, case.id)
    sections.append(
        ReportSection(
            heading="Case Overview",
            body=_fmt_lines(
                {
                    "Case": case.case_number,
                    "Title": case.title,
                    "Status": case.status,
                    "Priority": case.priority,
                    "Created": case.created_at.isoformat(),
                    "Entities associated": len(profiles),
                }
            ),
        )
    )

    sections.append(
        ReportSection(
            heading="Associated Entities",
            body=[f"{p.secret_id}  {p.name}  ({p.profile_type}, risk {p.risk_score})" for p in profiles]
            or ["No entities associated."],
        )
    )

    analytics = AnalyticsService(store)
    try:
        communities = await analytics.communities()
        sections.append(
            ReportSection(
                heading="Network Structure",
                body=[
                    f"Communities detected: {communities.count}",
                    f"Network density: {communities.network_density}",
                    *[
                        f"Community #{c.community_id}: {c.size} entities"
                        for c in communities.communities[:8]
                    ],
                ],
            )
        )
    except Exception:  # noqa: BLE001 - analytics unavailable should not break a report
        sections.append(
            ReportSection(heading="Network Structure", body=["Analytics unavailable for this case."])
        )

    return sections


async def build_entity_intelligence(
    session: AsyncSession,
    store,
    entity_id: str,
    title: str,
) -> list[ReportSection]:
    result = await session.execute(select(CriminalProfile).where(CriminalProfile.secret_id == entity_id))
    profile = result.scalar_one_or_none()

    if profile is None:
        return [
            ReportSection(
                heading="Entity Intelligence",
                body=[f"No profile found for {entity_id}.", "Report reflects no associated records."],
            )
        ]

    sections = [
        ReportSection(
            heading="Entity Overview",
            body=_fmt_lines(
                {
                    "Entity": profile.secret_id,
                    "Name": profile.name,
                    "Type": profile.profile_type,
                    "Risk score": profile.risk_score,
                    "Risk level": profile.risk_level,
                    "Confidence": profile.confidence,
                    "Status": profile.status,
                    "Aliases": ", ".join(profile.aliases or []),
                }
            ),
        )
    ]

    analytics = AnalyticsService(store)
    try:
        graph = await analytics._graph()
        node = graph.nodes.get(entity_id)
        if node is not None:
            degree = graph.degree(entity_id)
            neighbors = [n for n in graph.neighbors(entity_id)][:12]
            sections.append(
                ReportSection(
                    heading="Network Connections",
                    body=[f"Degree: {degree}", *[f"- {n}" for n in neighbors]],
                )
            )
    except Exception:  # noqa: BLE001
        sections.append(ReportSection(heading="Network Connections", body=["Unavailable."]))

    return sections


async def build_network_analysis(
    session: AsyncSession,
    store,
    title: str,
) -> list[ReportSection]:
    analytics = AnalyticsService(store)
    sections: list[ReportSection] = []

    try:
        communities = await analytics.communities()
        key_entities = await analytics.key_entities(top_k=10)
        links = await analytics.link_prediction(top_k=10)
        risk = await analytics.risk_assessment(run_anomalies=True)
    except Exception:  # noqa: BLE001
        return [
            ReportSection(heading="Network Analysis", body=["Analytics unavailable for this graph."])
        ]

    sections.append(
        ReportSection(
            heading="Community Structure",
            body=[
                f"Communities detected: {communities.count}",
                f"Network density: {communities.network_density}",
                *[f"Community #{c.community_id}: {c.size} entities" for c in communities.communities[:8]],
            ],
        )
    )

    sections.append(
        ReportSection(
            heading="Key Influencers",
            body=[
                f"{e.entity_id}  score={e.score}  factor={e.dominant_factor}"
                for e in key_entities.items
            ]
            or ["None identified."],
        )
    )

    sections.append(
        ReportSection(
            heading="Possible Hidden Links",
            body=[
                f"{l.source} <-> {l.target}  (score {l.score})" for l in links.candidates
            ]
            or ["None."],
        )
    )

    sections.append(
        ReportSection(
            heading="Risk Overview",
            body=[
                f"{r.entity_id}  {r.risk_level}  score={r.risk_score}"
                for r in risk.items[:10]
            ],
        )
    )

    if risk.anomalies:
        sections.append(
            ReportSection(
                heading="Flagged Anomalies",
                body=[f"- {a}" for a in risk.anomalies],
            )
        )

    return sections


async def build_transaction_analysis(session: AsyncSession, store, title: str) -> list[ReportSection]:
    # No dedicated transaction table in this phase; derive from graph TRANSFERRED_TO
    # edges present on entity accounts.
    analytics = AnalyticsService(store)
    try:
        graph = await analytics._graph()
    except Exception:  # noqa: BLE001
        return [ReportSection(heading="Transaction Analysis", body=["Unavailable."])]

    transfer_edges = [
        (a, b, d.get("type"))
        for a, b, d in graph.edges(data=True)
        if d.get("type") == "TRANSFERRED_TO"
    ]
    return [
        ReportSection(
            heading="Transaction Analysis",
            body=_fmt_lines({"Transfers mapped (synthetic)": len(transfer_edges)}),
        ),
        ReportSection(
            heading="Transfer Flows",
            body=[f"{a} -> {b}" for a, b, _ in transfer_edges] or ["No transfer edges present."],
        ),
    ]


async def build_communication_analysis(
    session: AsyncSession, store, title: str
) -> list[ReportSection]:
    analytics = AnalyticsService(store)
    try:
        graph = await analytics._graph()
    except Exception:  # noqa: BLE001
        return [ReportSection(heading="Communication Analysis", body=["Unavailable."])]

    comm_edges = [
        (a, b)
        for a, b, d in graph.edges(data=True)
        if d.get("type") in {"CALLED", "USES"}
    ]
    return [
        ReportSection(
            heading="Communication Analysis",
            body=_fmt_lines({"Communication links (synthetic)": len(comm_edges)}),
        ),
        ReportSection(
            heading="Frequent Contacts",
            body=[f"{a} <-> {b}" for a, b in comm_edges[:20]] or ["No communication edges present."],
        ),
    ]


BUILDERS = {
    "investigation_summary": build_investigation_summary,
    "entity_intelligence": build_entity_intelligence,
    "network_analysis": build_network_analysis,
    "transaction_analysis": build_transaction_analysis,
    "communication_analysis": build_communication_analysis,
}


def _status_label(status: str) -> str:
    return status.replace("_", " ").title()


async def _case_intelligence_sections(session: AsyncSession, case) -> list[ReportSection]:
    """Derived decision-support sections for a case.

    Every analytical claim is labelled OBSERVED / DERIVED / POTENTIAL /
    ANALYST CONFIRMED (or REJECTED/DEFERRED) and accompanied by its evidence
    ids. Indicators are never described as proof.
    """
    from app.services.case_intelligence_service import CaseIntelligenceService

    try:
        intel = await CaseIntelligenceService(session).build(case.id)
    except Exception:  # noqa: BLE001 - never break a report on a missing graph
        return [ReportSection(heading="Case Intelligence", body=["Intelligence unavailable."])]

    sections: list[ReportSection] = []

    if intel.get("potential_links"):
        rows: list[str] = []
        for link in intel["potential_links"][:10]:
            pair_key = "<->".join(sorted([link["source"], link["target"]]))
            decision = (intel.get("link_decisions") or {}).get(pair_key)
            status = "POTENTIAL"
            if decision and decision.get("new_status"):
                status = decision["new_status"]
            signals = "; ".join(link.get("supporting_signals", [])[:3])
            caveats = "; ".join(link.get("contradictory_signals", [])[:2]) or "requires confirmation"
            evidence = ", ".join(link.get("evidence_ids", [])[:6]) or "none"
            rows.append(
                f"- {link['source']} <-> {link['target']}  [{_status_label(status)}] "
                f"score {link.get('score', 0):.0f}  signals: {signals}  "
                f"caveat: {caveats}  evidence: {evidence}"
            )
        sections.append(ReportSection(heading="Potential Relationships (hypotheses)", body=rows))

    if intel.get("evidence_gaps"):
        sections.append(
            ReportSection(
                heading="Evidence Gaps",
                body=[
                    f"- {g.get('subject')}: missing {'; '.join(g.get('missing_evidence', []))} "
                    f"(recommended {g.get('recommended_source', 'CDR')} — {g.get('window', '')})"
                    for g in intel["evidence_gaps"][:10]
                ],
            )
        )

    if intel.get("anomalies"):
        sections.append(
            ReportSection(
                heading="Unusual Investigative Signals",
                body=[
                    f"- {a.get('kind')} {a.get('entity_id', '')}  baseline {a.get('baseline', 0)} / "
                    f"observed {a.get('observed', 0)}  ({a.get('deviation', 0):+.0f}%) — "
                    f"{a.get('explanation', '')}"
                    for a in intel["anomalies"][:10]
                ],
            )
        )

    if intel.get("recommendations"):
        sections.append(
            ReportSection(
                heading="Next Best Actions",
                body=[
                    f"- {r.get('kind')} {r.get('subject')} — {', '.join(r.get('reasoning', [])[:2])} "
                    f"(data: {r.get('recommended_data', '')})"
                    for r in intel["recommendations"][:8]
                ],
            )
        )

    dna = intel.get("network_dna")
    if dna:
        sections.append(
            ReportSection(
                heading="Network Structure",
                body=_fmt_lines({
                    "Entities": len(intel.get("entities", [])),
                    "Relationships": len(intel.get("relationships", [])),
                    "Communities": dna.get("community_count", 0),
                    "Density": dna.get("density", 0),
                    "Bridge dependence": dna.get("bridge_dependence", "LOW"),
                    "Evidence coverage": f"{dna.get('evidence_coverage', 0)}%",
                }),
            )
        )

    sections.append(
        ReportSection(
            heading="Analytical Caveats",
            body=[
                "All signals are decision-support indicators produced by deterministic "
                "analysis, not findings of wrongdoing. Nothing here proves guilt.",
                "Potential relationships and anomaly scores require analyst review and "
                "independent corroboration before operational use.",
                "This report is generated from synthetic demonstration data unless a live "
                "backend with reviewed sources is connected.",
            ],
        )
    )

    return sections
