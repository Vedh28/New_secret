"""Potential / hidden link discovery (Phase 6).

Finds entity pairs that are NOT directly connected but share multiple indirect
signals. Builds on the existing Adamic-Adar link predictor and adds explainable
supporting signals: shared organization, shared location, common intermediary,
temporal overlap. Results are POTENTIAL relationships, never confirmed.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from app.analytics.graph_builder import build_graph
from app.analytics.link_prediction import predict_links
from app.graph.types import GraphSubgraph
from app.intelligence.models import CaseData, PotentialLink


def _add_signal(signals: list[str], label: str) -> None:
    if label not in signals:
        signals.append(label)


def _shared_locations(data: CaseData) -> dict[tuple[str, str], int]:
    """Count shared location entities between entity PAIRS, following each
    person's device/vehicle link to that device's observed locations (2 hops)."""
    adj: dict[str, set[str]] = defaultdict(set)
    for r in data.relationships:
        adj[r.source].add(r.target)
        adj[r.target].add(r.source)

    loc_of: dict[str, set[str]] = defaultdict(set)   # entity -> locations
    for r in data.relationships:
        if r.rel_type in ("USES", "VISITED", "LOCATED_AT"):
            loc_id = r.target
            loc = data.entity(loc_id)
            if loc and loc.type.upper() == "LOCATION":
                loc_of[r.source].add(loc_id)
                # resolve who owns/uses the source device
                for owner in adj.get(r.source, ()):
                    if not _is_location(data, owner) and not _is_org(data, owner):
                        loc_of[owner].add(loc_id)

    people = [e for e in data.entities if not _is_location(data, e.id) and not _is_org(data, e.id)]
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for i in range(len(people)):
        for j in range(i + 1, len(people)):
            a, b = people[i].id, people[j].id
            common = loc_of[a] & loc_of[b]
            if common:
                shared[tuple(sorted((a, b)))] += len(common)
    return shared


def _support_sources(data: CaseData, a: str, b: str) -> dict[str, list[str]]:
    """Map each supporting-signal kind to the source ids that back it.

    Provenance for the potential-link hypothesis: never invent source ids,
    only reuse ids already attached to relationships / evidence.
    """
    out: dict[str, list[str]] = {k: [] for k in
                                 ("org", "loc", "intermediary", "overlap", "structural")}

    def _append(dst: list[str], *values: str) -> None:
        for v in values:
            if v and v not in dst:
                dst.append(v)

    # Shared organization.
    org_a: dict[str, list[str]] = defaultdict(list)
    org_b: dict[str, list[str]] = defaultdict(list)
    for r in data.relationships:
        if r.rel_type == "MEMBER_OF":
            if r.source == a:
                org_a[r.target].extend(r.source_ids or [])
            elif r.source == b:
                org_b[r.target].extend(r.source_ids or [])
    for org in set(org_a) & set(org_b):
        _append(out["org"], *org_a[org], *org_b[org])

    # Shared locations (via 2-hop device/vehicle links).
    adj: dict[str, set[str]] = defaultdict(set)
    for r in data.relationships:
        adj[r.source].add(r.target)
        adj[r.target].add(r.source)
    loc_of: dict[str, set[str]] = defaultdict(set)
    for r in data.relationships:
        if r.rel_type in ("USES", "VISITED", "LOCATED_AT"):
            loc_id = r.target
            loc = data.entity(loc_id)
            if loc and loc.type.upper() == "LOCATION":
                loc_of[r.source].add(loc_id)
                for owner in adj.get(r.source, ()):
                    if loc_id not in loc_of[owner]:
                        loc_of[owner].add(loc_id)
    for loc in loc_of.get(a, set()) & loc_of.get(b, set()):
        for r in data.relationships:
            if r.rel_type in ("USES", "VISITED", "LOCATED_AT") and r.target == loc:
                if r.source in (a, b) or r.source in adj.get(a, set()) or r.source in adj.get(b, set()):
                    _append(out["loc"], *(r.source_ids or []))

    # Common intermediary.
    na, nb = adj.get(a, set()), adj.get(b, set())
    for n in na & nb:
        for r in data.relationships:
            pair = {r.source, r.target}
            if n in pair and (a in pair or b in pair):
                _append(out["intermediary"], *(r.source_ids or []))

    # Temporal overlap: relationships sharing an activity hour-bucket.
    buckets: dict[str, set[str]] = defaultdict(set)
    for r in data.relationships:
        for ts in r.timestamps:
            dt = _parse_ts(ts)
            if dt:
                buckets[dt.strftime("%Y-%m-%dT%H")].add(r.source)
                buckets[dt.strftime("%Y-%m-%dT%H")].add(r.target)
    for hour, entities in buckets.items():
        if a in entities and b in entities:
            for r in data.relationships:
                if r.source in (a, b) and _parse_ts(r.first_seen or r.last_seen):
                    if _parse_ts(r.first_seen or r.last_seen).strftime("%Y-%m-%dT%H") == hour:
                        _append(out["overlap"], *(r.source_ids or []))

    # Structural similarity: any evidence naming either endpoint.
    for e in data.evidence:
        if a in e.entity_ids or b in e.entity_ids:
            _append(out["structural"], e.source_id)

    return out


def _parse_ts(value: str):
    from datetime import datetime as _dt
    try:
        return _dt.fromisoformat(value.replace(" ", "T"))
    except (ValueError, TypeError):
        return None


def _is_location(data: CaseData, entity_id: str) -> bool:
    e = data.entity(entity_id)
    return bool(e and e.type.upper() == "LOCATION")


def _shared_org(data: CaseData) -> dict[tuple[str, str], int]:
    """Pair people belonging to the same organization."""
    members: dict[str, set[str]] = defaultdict(set)
    for r in data.relationships:
        if r.rel_type == "MEMBER_OF":
            members[r.target].add(r.source)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for org, people in members.items():
        people = list(people)
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                shared[tuple(sorted((people[i], people[j])))] += 1
    return shared


def _temporal_overlap(data: CaseData) -> dict[tuple[str, str], int]:
    """People whose activity overlaps in time windows."""
    when: dict[str, set[str]] = defaultdict(set)  # hour -> entities active
    for r in data.relationships:
        for ts in r.timestamps:
            dt = None
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(ts.replace(" ", "T"))
            except ValueError:
                continue
            if dt:
                key = dt.strftime("%Y-%m-%dT%H")
                when[key].add(r.source)
                when[key].add(r.target)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for hour, people in when.items():
        people = list(people)
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                shared[tuple(sorted((people[i], people[j])))] += 1
    return shared


def _common_intermediary(data: CaseData) -> dict[tuple[str, str], int]:
    """People connected by at least one common neighbor."""
    adj: dict[str, set[str]] = defaultdict(set)
    for r in data.relationships:
        adj[r.source].add(r.target)
        adj[r.target].add(r.source)
    shared: dict[tuple[str, str], int] = defaultdict(int)
    for node, neighbors in adj.items():
        nlist = list(n for n in neighbors if not _is_location(data, n) and not _is_org(data, n))
        for i in range(len(nlist)):
            for j in range(i + 1, len(nlist)):
                shared[tuple(sorted((nlist[i], nlist[j])))] += 1
    return shared


def _is_org(data: CaseData, entity_id: str) -> bool:
    e = data.entity(entity_id)
    return bool(e and e.type.upper() in ("ORGANIZATION", "ORG"))


def discover(data: CaseData, top_k: int = 10) -> list[PotentialLink]:
    """Rank potential (non-direct) relationships by multi-signal strength."""
    if len(data.entities) < 2:
        return []

    # Structural link-prediction signal from the persisted network.
    subgraph = GraphSubgraph(
        nodes=[n for n in _subgraph_nodes(data)],
        edges=[e for e in _subgraph_edges(data)],
    )
    structural = {}
    for cand in predict_links(build_graph(subgraph), top_k=top_k * 4):
        structural[(cand["source"], cand["target"])] = cand["score"]

    shr_loc = _shared_locations(data)
    shr_org = _shared_org(data)
    overlap = _temporal_overlap(data)
    intermediary = _common_intermediary(data)

    candidates: dict[tuple[str, str], dict] = {}
    for a in data.entities:
        for b in data.entities:
            if a.id >= b.id:
                continue
            pair = (a.id, b.id)
            # Skip direct relationships.
            if any((r.source == a.id and r.target == b.id) or (r.source == b.id and r.target == a.id)
                   for r in data.relationships):
                continue
            if pair in candidates or tuple(reversed(pair)) in candidates:
                continue
            candidates[pair] = {
                "struct": structural.get(pair, structural.get(tuple(reversed(pair)), 0.0)),
                "loc": shr_loc.get(pair, 0),
                "org": shr_org.get(pair, 0),
                "overlap": overlap.get(pair, 0),
                "inter": intermediary.get(pair, 0),
            }

    results: list[PotentialLink] = []
    for (a, b), sig in candidates.items():
        score = (
            sig["struct"] * 0.4
            + min(25.0, sig["org"] * 12.0)
            + min(20.0, sig["loc"] * 10.0)
            + min(25.0, sig["overlap"] * 2.0)
            + min(20.0, sig["inter"] * 8.0)
        )
        if score <= 5:
            continue
        signals: list[str] = []
        if sig["org"]:
            _add_signal(signals, f"Shared organization ({sig['org']})")
        if sig["loc"]:
            _add_signal(signals, f"Shared location ({sig['loc']})")
        if sig["inter"]:
            _add_signal(signals, f"Common intermediary ({sig['inter']})")
        if sig["overlap"]:
            _add_signal(signals, f"Temporal overlap ({sig['overlap']})")
        if sig["struct"]:
            _add_signal(signals, f"Structural similarity ({sig['struct']:.0f}/100)")

        # Provenance: source ids backing each signal, deduped, never invented.
        support_sources = _support_sources(data, a, b)
        evidence_ids: list[str] = []
        for kind in ("org", "loc", "intermediary", "overlap"):
            evidence_ids.extend(support_sources[kind])
        evidence_ids = list(dict.fromkeys(evidence_ids))

        # Why is this still POTENTIAL? Surface the contradictory/missing facts.
        contradictory = _contradictory_signals(data, a, b, evidence_ids)

        results.append(
            PotentialLink(
                source=a,
                target=b,
                score=round(min(100.0, score), 1),
                supporting_signals=signals,
                contradictory_signals=contradictory,
                evidence_ids=evidence_ids,
                confidence=round(score / 100.0, 2),
                explanation=_explain(a, b, signals, contradictory),
            )
        )

    results.sort(key=lambda p: p.score, reverse=True)
    # Deduplicate by unordered pair.
    seen: set[tuple[str, str]] = set()
    deduped: list[PotentialLink] = []
    for p in results:
        key = tuple(sorted((p.source, p.target)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped[:top_k]


def _subgraph_nodes(data: CaseData):
    from app.graph.types import GraphNode

    return [
        GraphNode(id=e.id, type=e.type, name=e.name, properties={"type": e.type})
        for e in data.entities
    ]


def _subgraph_edges(data: CaseData):
    from app.graph.types import GraphEdge

    return [
        GraphEdge(id="", source_id=r.source, target_id=r.target, type=r.rel_type,
                  properties={"confidence": r.confidence})
        for r in data.relationships
    ]


def _contradictory_signals(data: CaseData, a: str, b: str, evidence_ids: list[str]) -> list[str]:
    """Explain why a pair remains POTENTIAL rather than observed/confirmed."""
    out: list[str] = []
    has_direct = any(
        (r.source == a and r.target == b) or (r.source == b and r.target == a)
        for r in data.relationships
    )
    if not has_direct:
        out.append("no direct communication or transfer observed")
    src_types = {e.source_type for e in data.evidence
                 if (a in e.entity_ids or b in e.entity_ids) and e.source_id in evidence_ids}
    all_types = {e.source_type for e in data.evidence if a in e.entity_ids or b in e.entity_ids}
    if len(all_types) < 2 and all_types:
        out.append("supported by a single source type only")
    if not evidence_ids and not has_direct:
        out.append("no evidence-backed corroboration yet")
    return out


def _explain(a: str, b: str, signals: list[str], contradictory: list[str] | None = None) -> str:
    contradictory = contradictory or []
    if not signals:
        return f"{a} and {b} share weak indirect signals (below reporting threshold)."
    base = f"{a} ↔ {b} is a POTENTIAL relationship (not observed directly) supported by: " \
           f"{'; '.join(signals)}. Requires confirmation before treating as a link."
    if contradictory:
        base += " Caveats: " + "; ".join(contradictory) + "."
    return base