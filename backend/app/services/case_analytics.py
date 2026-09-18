"""Per-case analytical read-models (Phase comms/tx/timeline/location).

All numbers are computed from persisted ingestion data (relationships + source
records) — no canned values.
"""
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.entity_repository import EntityRepository, RelationshipRepository
from app.repositories.source_repository import SourceRepository


# Prototype geospatial resolver. External geocoding can replace this later;
# unknown places remain coordinate-less instead of being placed inaccurately.
_KNOWN_LOCATION_COORDINATES: dict[str, tuple[float, float]] = {
    "bandra": (19.0607, 72.8362),
    "mumbai": (19.0760, 72.8777),
    "mumbai-pune highway": (18.9890, 73.1170),
    "pune": (18.5204, 73.8567),
    "budhwar peth": (18.5162, 73.8567),
    "dharavi": (19.0370, 72.8560),
    "mansarovar": (26.8560, 75.7640),
    "jaipur": (26.9124, 75.7873),
    "delhi": (28.6139, 77.2090),
    "bengal": (22.5726, 88.3639),
    "kolkata": (22.5726, 88.3639),
    "hyderabad": (17.3850, 78.4867),
}


def _resolve_coordinates(name: str) -> tuple[float, float] | None:
    normalized = name.strip().lower()
    # Match specific landmarks before broad city names (e.g. highway before Mumbai).
    for place in sorted(_KNOWN_LOCATION_COORDINATES, key=len, reverse=True):
        if place in normalized:
            return _KNOWN_LOCATION_COORDINATES[place]
    return None

_COMM_REL_TYPES = ("CALLED", "MESSAGED")
_TX_REL_TYPES = ("TRANSFERRED_TO",)

DEFAULT_WINDOW_MS = 3_600_000  # 1 h buckets


def _window_key(timestamp: str, bucket_ms: int) -> str | None:
    if not timestamp:
        return None
    ts = timestamp.strip()
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(ts.replace(" ", "T"))
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:00") if bucket_ms == 3_600_000 else dt.strftime("%Y-%m-%dT%H:%M")


def _rel_weight(rel) -> int:
    return max(1, int(rel.attributes.get("count") or 1))


def _window_key_list(attributes: dict) -> list[str]:
    """Per-record windows from a relationship's persisted timestamps."""
    timestamps = attributes.get("timestamps") or []
    windows: list[str] = []
    for ts in timestamps:
        window = _window_key(str(ts), DEFAULT_WINDOW_MS)
        if window:
            windows.append(window)
    if not windows:
        fallback = _window_key(str(attributes.get("last_seen") or attributes.get("first_seen") or ""), DEFAULT_WINDOW_MS)
        if fallback:
            windows.append(fallback)
    return windows


class CaseAnalyticsService:
    """Analytics over one case's persisted entities/relationships."""

    def __init__(self, session: AsyncSession) -> None:
        self._relationships = RelationshipRepository(session)
        self._entities = EntityRepository(session)
        self._sources = SourceRepository(session)

    async def communications(self, case_id: int) -> dict[str, Any]:
        rels = [r for r in await self._relationships.list_by_case(case_id) if r.rel_type in _COMM_REL_TYPES]
        flows: Counter[tuple[str, str]] = Counter()
        entity_count: Counter[str] = Counter()
        bursts: Counter[tuple[str, str]] = Counter()

        for rel in rels:
            weight = _rel_weight(rel)
            flows[(rel.source_id, rel.target_id)] += weight
            entity_count[rel.source_id] += weight
            entity_count[rel.target_id] += weight
            for window in _window_key_list(rel.attributes):
                bursts[(rel.source_id, window)] += 1

        return {
            "total_communications": sum(flows.values()),
            "top_contacts": [
                {"entity_id": eid, "count": n}
                for eid, n in entity_count.most_common(10)
            ],
            "flows": [
                {"source": s, "target": t, "count": n}
                for (s, t), n in flows.most_common(20)
            ],
            "bursts": [
                {"entity_id": eid, "window": win, "count": n}
                for (eid, win), n in sorted(bursts.items(), key=lambda kv: -kv[1])[:10]
            ],
        }

    async def transactions(self, case_id: int) -> dict[str, Any]:
        rels = [r for r in await self._relationships.list_by_case(case_id) if r.rel_type in _TX_REL_TYPES]
        amounts: Counter[tuple[str, str]] = Counter()
        counts: Counter[tuple[str, str]] = Counter()
        sender_total: Counter[str] = Counter()

        for rel in rels:
            amount = rel.attributes.get("amount")
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                amount = 0.0
            weight = _rel_weight(rel)
            amounts[(rel.source_id, rel.target_id)] += amount * weight
            counts[(rel.source_id, rel.target_id)] += weight
            sender_total[rel.source_id] += amount * weight

        return {
            "total_transactions": sum(counts.values()),
            "total_amount": sum(amounts.values()),
            "flows": [
                {"source": s, "target": t, "count": counts[(s, t)], "total_amount": round(amounts[(s, t)], 2)}
                for s, t in amounts
            ],
            "top_senders": [
                {"account_id": aid, "total_amount": round(total, 2), "count": sum(c for (s, t), c in counts.items() if s == aid)}
                for aid, total in sender_total.most_common(10)
            ],
        }

    async def timeline(self, case_id: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for source in await self._sources.list_by_case(case_id):
            meta = source.metadata_json or {}
            records = meta.get("records") or []
            if not records and meta.get("text"):
                events.append(
                    {
                        "timestamp": "",
                        "record_id": source.source_id,
                        "source_id": source.source_id,
                        "summary": (meta.get("text") or "")[:200],
                        "location": None,
                    }
                )
                continue
            for rec in records:
                fields = rec.get("fields") or {}
                ts = str(rec.get("timestamp") or "")
                summary = _summarize(source.source_id, rec.get("source_type") or source.source_type or "", fields, rec.get("text") or "")
                location = fields.get("location") or fields.get("area") or None
                events.append(
                    {
                        "timestamp": ts,
                        "record_id": str(rec.get("id") or ""),
                        "source_id": source.source_id,
                        "summary": summary,
                        "location": location,
                    }
                )

        def _key(e: dict) -> str:
            return e["timestamp"] or "\uffff"  # untimestamped events sort last

        events.sort(key=_key)
        return events

    async def locations(self, case_id: int) -> dict[str, Any]:
        entities = await self._entities.list_by_case(case_id)
        relationships = await self._relationships.list_by_case(case_id)
        entity_names = {e.entity_id: e.name for e in entities}
        linked_by_location = {
            r.target_id: r.source_id
            for r in relationships
            if r.rel_type == "LOCATED_AT"
        }
        area_count: Counter[str] = Counter()
        visits: list[dict[str, Any]] = []
        for e in entities:
            if e.entity_type != "LOCATION":
                continue
            area = e.name or e.entity_id
            area_count[area] += 1
            attrs = e.attributes or {}
            coordinates = _resolve_coordinates(area)
            visits.append(
                {
                    "location": area,
                    "entity_id": e.entity_id,
                    "linked_entity_id": linked_by_location.get(e.entity_id),
                    "linked_entity_name": entity_names.get(linked_by_location.get(e.entity_id, "")),
                    "latitude": attrs.get("latitude") or (coordinates[0] if coordinates else None),
                    "longitude": attrs.get("longitude") or (coordinates[1] if coordinates else None),
                    "observations": area_count[area],
                }
            )
        return {
            "locations": [{"name": name, "observations": n} for name, n in area_count.most_common()],
            "visits": visits,
        }


def _summarize(source_type: str, record_source_type: str, fields: dict, text: str) -> str:
    """Human-readable summary from a canonical record."""
    if fields.get("caller_phone") and fields.get("receiver_phone"):
        return f"{fields['caller_phone']} called {fields['receiver_phone']}"
    if fields.get("receiver_phone"):
        return f"Received call (receiver {fields['receiver_phone']})"
    if fields.get("sender") and fields.get("receiver"):
        amount = fields.get("amount") or ""
        return f"{fields['sender']} transferred {amount} to {fields['receiver']}".strip()
    if fields.get("vehicle") and fields.get("owner"):
        return f"{fields['owner']} registered vehicle {fields['vehicle']}"
    if fields.get("location"):
        return f"Observed at {fields['location']}"
    snippet = (text or "").strip().replace("\n", " ")[:200]
    if snippet:
        return snippet
    return f"{source_type} / {record_source_type} record"
