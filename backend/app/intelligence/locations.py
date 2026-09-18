"""Case-scoped location observations (P1-9).

Derives a location observation count from a case's OWN persisted data — never
from a global or offline map. Every USES / VISITED / LOCATED_AT relationship
whose target is a LOCATION entity counts as one observation for that location;
LOCATION-typed evidence records also contribute. This keeps anomaly and
geospatial intelligence strictly case-scoped and free of live/demo mixing.
"""
from __future__ import annotations

from collections import Counter

from app.intelligence.models import CaseData

_OBSERVED_REL_TYPES = ("USES", "VISITED", "LOCATED_AT")


def case_location_observations(data: CaseData) -> dict[str, int]:
    """Count location observations recorded for THIS case."""
    observations: Counter[str] = Counter()

    for rel in data.relationships:
        if rel.rel_type not in _OBSERVED_REL_TYPES:
            continue
        location = data.entity(rel.target)
        if location is None or location.type.upper() != "LOCATION":
            continue
        name = location.name or location.id
        observations[name] += 1

    for ev in data.evidence:
        if ev.source_type.upper() != "LOCATION":
            continue
        for entity_id in ev.entity_ids:
            entity = data.entity(entity_id)
            if entity is not None and entity.type.upper() == "LOCATION":
                observations[entity.name or entity.id] += 1

    return dict(observations)