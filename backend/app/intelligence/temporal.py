"""Temporal network intelligence (Phase 4).

Builds BEFORE/AFTER snapshots of the network over time and detects evolution:
new/dropped relationships, strengthened/weakened, emerging bridges, and
activity bursts. Deterministic; every change carries an explanation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.intelligence.models import CaseData, RelData, TemporalChange


def _parse(value: str) -> datetime | None:
    """Parse an ISO timestamp, normalizing timezone-aware values to UTC-naive.

    Naive and aware timestamps may coexist across sources; comparing one of
    each raises TypeError. Normalizing aware -> UTC and dropping tzinfo gives a
    single comparable clock. Invalid/missing values return None.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace(" ", "T"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def split_at(data: CaseData, boundary: str) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """Return (before, after) sets of (source, target, type) for the boundary.

    BEFORE: relationship whose first observation is <= boundary.
    AFTER:  relationship whose first observation is > boundary.
    Untimed or invalid timestamps fall into neither slice when a boundary is
    given (their temporal position is unknown, so they must not be reported as
    new/emerging). With no boundary, everything is BEFORE.
    """
    cutoff = _parse(boundary)
    before: set[tuple[str, str, str]] = set()
    after: set[tuple[str, str, str]] = set()
    for r in data.relationships:
        seen = _parse(r.first_seen or r.last_seen)
        key = (r.source, r.target, r.rel_type)
        if cutoff is None:
            before.add(key)
        elif seen is not None:
            if seen <= cutoff:
                before.add(key)
            else:
                after.add(key)
    return before, after


def relationship_trends(data: CaseData) -> list[TemporalChange]:
    """Detect strengthened/weakened relationships using per-rel counts."""
    changes: list[TemporalChange] = []
    for r in data.relationships:
        if r.count >= 3:
            changes.append(
                TemporalChange(
                    kind="STRENGTHENED",
                    source=r.source,
                    target=r.target,
                    after=float(r.count),
                    score=min(100.0, r.strength * 100.0),
                    explanation=f"{r.source}-{r.target} has {r.count} recorded interactions "
                                f"({r.rel_type}), indicating sustained activity.",
                )
            )
    return changes


def network_evolution(data: CaseData, boundary: str) -> list[TemporalChange]:
    """Diff before/after snapshots and describe the evolution."""
    before, after = split_at(data, boundary)
    new = after - before
    dropped = before - after
    changes: list[TemporalChange] = []

    for src, tgt, rel_type in sorted(new):
        changes.append(
            TemporalChange(
                kind="NEW_REL",
                source=src,
                target=tgt,
                after=1.0,
                score=15.0,
                explanation=f"New {rel_type} relationship appeared between {src} and {tgt} "
                            f"after {boundary}.",
            )
        )
    for src, tgt, rel_type in sorted(dropped):
        changes.append(
            TemporalChange(
                kind="DROPPED_REL",
                source=src,
                target=tgt,
                before=1.0,
                score=15.0,
                explanation=f"{rel_type} between {src} and {tgt} was present before {boundary} "
                            f"and not observed after.",
            )
        )
    return changes


def emerging_bridges(data: CaseData, communities: list[list[str]], boundary: str) -> list[TemporalChange]:
    """Flag nodes that connected new cross-community pairs after `boundary`.

    Only relationships observed strictly AFTER the boundary may count; a
    cross-community edge that existed before the split must never be reported
    as an emerging bridge.
    """
    _, after = split_at(data, boundary)
    comm_of: dict[str, int] = {}
    for i, members in enumerate(communities):
        for m in members:
            comm_of[m] = i

    # count cross-community edges added after boundary per node
    added_after: dict[str, int] = defaultdict(int)
    for src, tgt, _rtype in after:
        if comm_of.get(src) is not None and comm_of.get(tgt) is not None and comm_of[src] != comm_of[tgt]:
            added_after[src] += 1
            added_after[tgt] += 1

    changes: list[TemporalChange] = []
    for node, n in sorted(added_after.items(), key=lambda kv: -kv[1]):
        if n >= 1:
            changes.append(
                TemporalChange(
                    kind="EMERGING_BRIDGE",
                    source=node,
                    after=float(n),
                    score=min(100.0, 30.0 + n * 20.0),
                    explanation=f"{node} gained {n} cross-community connection(s) after "
                                f"{boundary}, making it a potential bridge between previously "
                                f"separate groups.",
                )
            )
    return changes


def activity_bursts(relationships: list[RelData], min_count: int = 4) -> list[TemporalChange]:
    """Flag relationships with a high interaction count (communication/tx bursts)."""
    out: list[TemporalChange] = []
    for r in relationships:
        if r.count >= min_count:
            out.append(
                TemporalChange(
                    kind="BURST",
                    source=r.source,
                    target=r.target,
                    before=1.0,
                    after=float(r.count),
                    score=min(100.0, 30.0 + r.count * 10.0),
                    explanation=f"Burst of {r.count} {r.rel_type} interactions between "
                                f"{r.source} and {r.target}.",
                )
            )
    return out


def default_boundary(data: CaseData) -> str:
    """P75 of observed first-seen timestamps — biases the split toward the
    latest activity cluster so new/strengthened relationships appear in the
    AFTER slice. Untimed relationships are ignored."""
    ts = [_parse(t) for r in data.relationships for t in (r.first_seen or r.last_seen,)]
    ts = sorted(t for t in ts if t is not None)
    if not ts:
        return ""
    idx = min(len(ts) - 1, int(len(ts) * 0.75))
    return ts[idx].strftime("%Y-%m-%dT%H:%M")