"""Anomaly intelligence (Phase 5).

Deterministic anomaly detection over persisted signals: communication bursts,
transaction amounts/frequency, location activity, new relationship creation,
and structural outliers. Every anomaly reports baseline, observed value,
deviation, score, timestamp, evidence and an explanation. Analytical language
only — never criminality.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.intelligence.models import Anomaly, CaseData, RelData


def _parse(value: str) -> datetime | None:
    """Parse an ISO timestamp, normalizing timezone-aware values to UTC-naive.

    Mixed naive/aware timestamps across sources otherwise raise TypeError on
    naive/aware comparison; normalizing to a single UTC clock avoids that.
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


def _hour(value: str) -> str | None:
    dt = _parse(value)
    return dt.strftime("%Y-%m-%dT%H:00") if dt else None


def _zscore(deviation_pct: float) -> float:
    # Map percentage deviation to a 0..100 anomaly score (clamped).
    return round(min(max(abs(deviation_pct) / 3.0, 0.0), 100.0), 1)


def communication_bursts(relationships: list[RelData], hour_threshold: int = 3) -> list[Anomaly]:
    """Flag entities with an unusual number of comm events in a single hour."""
    by_entity_hour: dict[str, Counter[str]] = defaultdict(Counter)
    all_counts: list[int] = []
    for rel in relationships:
        if rel.rel_type not in ("CALLED", "MESSAGED"):
            continue
        for ts in rel.timestamps:
            h = _hour(ts)
            if h:
                by_entity_hour[rel.source][h] += 1
                all_counts.append(by_entity_hour[rel.source][h])

    if not all_counts:
        return []
    baseline = sorted(all_counts)[len(all_counts) // 2] or 1
    anomalies: list[Anomaly] = []
    for entity, hours in by_entity_hour.items():
        for hour, count in hours.items():
            if count >= hour_threshold and count >= 2 * baseline:
                dev = round((count - baseline) * 100.0 / baseline, 1)
                anomalies.append(
                    Anomaly(
                        kind="COMM_BURST",
                        entity_id=entity,
                        baseline=float(baseline),
                        observed=float(count),
                        deviation=dev,
                        score=_zscore(dev),
                        timestamp=hour,
                        evidence=[f"{count} events in {hour} window"],
                        explanation=f"Baseline {baseline}/hr, observed {count}/hr (+{dev}%) — "
                                    f"an unusual communication burst, investigative signal only.",
                    )
                )
    return anomalies


def _median(values: list[float]) -> float:
    """Lower-median for even lists (robust, matching typical statistical median)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def transaction_amounts(relationships: list[RelData], tx_types=("TRANSFERRED_TO",)) -> list[Anomaly]:
    """Flag transactions whose amount deviates sharply from the case median."""
    amounts = [r.amount for r in relationships if r.rel_type in tx_types and r.amount > 0]
    if not amounts:
        return []
    median = _median(amounts)
    if median <= 0:
        return []
    anomalies: list[Anomaly] = []
    for rel in relationships:
        if rel.rel_type not in tx_types or rel.amount <= 0:
            continue
        dev = round((rel.amount - median) * 100.0 / median, 1)
        if rel.amount >= 3 * median:
            anomalies.append(
                Anomaly(
                    kind="TX_AMOUNT",
                    entity_id=f"{rel.source}->{rel.target}",
                    baseline=median,
                    observed=rel.amount,
                    deviation=dev,
                    score=_zscore(dev),
                    timestamp=rel.last_seen,
                    evidence=[f"amount {rel.amount:,.0f} vs median {median:,.0f}"],
                    explanation=f"Transfer amount {rel.amount:,.0f} is {dev:+.0f}% from the "
                                f"case median {median:,.0f} — an unusual financial signal.",
                )
            )
    return anomalies


def transaction_frequency(relationships: list[RelData], tx_types=("TRANSFERRED_TO",)) -> list[Anomaly]:
    """Flag relationship pairs whose transfer COUNT deviates from the peer median."""
    counts = [r.count for r in relationships if r.rel_type in tx_types and r.count > 0]
    if len(counts) < 3:
        return []
    baseline = _median(counts)
    if baseline <= 0:
        return []
    anomalies: list[Anomaly] = []
    for rel in relationships:
        if rel.rel_type not in tx_types or rel.count <= 0:
            continue
        if rel.count >= 2 * baseline:
            dev = round((rel.count - baseline) * 100.0 / baseline, 1)
            anomalies.append(
                Anomaly(
                    kind="TX_FREQUENCY",
                    entity_id=f"{rel.source}->{rel.target}",
                    baseline=float(baseline),
                    observed=float(rel.count),
                    deviation=dev,
                    score=min(100.0, _zscore(dev) + 15.0),
                    timestamp=rel.last_seen,
                    evidence=[f"{rel.count} transfers vs peer median {baseline:.0f}"],
                    explanation=f"{rel.source}->{rel.target} exchanges funds {rel.count} times, "
                                f"{dev:+.0f}% above the peer median — a frequency anomaly, "
                                f"investigative signal only.",
                )
            )
    return anomalies


def transaction_velocity(relationships: list[RelData], tx_types=("TRANSFERRED_TO",), per_hour: int = 2) -> list[Anomaly]:
    """Flag rapid-fire transfers between a pair within a short window."""
    windowed: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for rel in relationships:
        if rel.rel_type not in tx_types:
            continue
        for ts in rel.timestamps:
            h = _hour(ts)
            if h:
                windowed[(rel.source, rel.target)][h] += 1
    anomalies: list[Anomaly] = []
    for (source, target), hours in windowed.items():
        for hour, count in hours.items():
            if count >= per_hour:
                anomalies.append(
                    Anomaly(
                        kind="TX_VELOCITY",
                        entity_id=f"{source}->{target}",
                        baseline=1.0,
                        observed=float(count),
                        deviation=round((count - 1) * 100.0, 1),
                        score=min(100.0, 40.0 + count * 15.0),
                        timestamp=hour,
                        evidence=[f"{count} transfers from {source}->{target} in {hour} window"],
                        explanation=f"{count} rapid transfers between {source} and {target} in one "
                                    f"hour — unusual flow velocity, investigative signal only.",
                    )
                )
    return anomalies


def new_relationship_anomalies(relationships: list[RelData], window_days: int = 14) -> list[Anomaly]:
    """Flag relationships observed only in a recent window (potential new links)."""
    now = max((_parse(r.last_seen) for r in relationships if _parse(r.last_seen)), default=None)
    if now is None:
        return []
    cutoff = now - timedelta(days=window_days)
    anomalies: list[Anomaly] = []
    for rel in relationships:
        seen = _parse(rel.first_seen)
        if seen and seen >= cutoff and rel.count <= 1:
            anomalies.append(
                Anomaly(
                    kind="REL_NEW",
                    entity_id=f"{rel.source}->{rel.target}",
                    observed=1.0,
                    deviation=100.0,
                    score=60.0,
                    timestamp=rel.first_seen,
                    evidence=[f"first seen {rel.first_seen}"],
                    explanation=f"Relationship {rel.source}-{rel.target} is new in the last "
                                f"{window_days} days with a single observation.",
                )
            )
    return anomalies


def location_anomalies(entities, observations: dict[str, int]) -> list[Anomaly]:
    """Flag locations with a disproportionate share of entity observations."""
    total = sum(observations.values())
    if total <= 0:
        return []
    # balance: >35% of all observations at one place is a hotspot.
    anomalies: list[Anomaly] = []
    for loc, n in observations.items():
        share = n * 100.0 / total
        if share >= 35.0:
            anomalies.append(
                Anomaly(
                    kind="LOCATION",
                    entity_id=loc,
                    baseline=round(total / max(len(observations), 1), 1),
                    observed=float(n),
                    deviation=round(share - (100.0 / max(len(observations), 1)), 1),
                    score=round(share, 1),
                    evidence=[f"{n} observations ({share:.0f}% of total)"],
                    explanation=f"Location {loc} concentrates {share:.0f}% of entity activity "
                                f"across {len(observations)} sites.",
                )
            )
    return anomalies


def detect_all(data: CaseData, location_observations: dict[str, int] | None = None) -> list[Anomaly]:
    """Run all deterministic anomaly detectors over a case snapshot."""
    anomalies: list[Anomaly] = []
    anomalies += communication_bursts(data.relationships)
    anomalies += transaction_amounts(data.relationships)
    anomalies += transaction_frequency(data.relationships)
    anomalies += transaction_velocity(data.relationships)
    anomalies += new_relationship_anomalies(data.relationships)
    if location_observations:
        anomalies += location_anomalies(data.entities, location_observations)
    anomalies.sort(key=lambda a: a.score, reverse=True)
    return anomalies