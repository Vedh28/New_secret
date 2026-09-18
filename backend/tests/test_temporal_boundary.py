"""P0.3 regression: emerging bridges must respect the temporal boundary.

A relationship that existed BEFORE the split must never be classified as an
EMERGING_BRIDGE after the boundary. The temporal intelligence engines must
produce clean BEFORE / AFTER sets using normalised timestamps.
"""
from __future__ import annotations

import pytest

from app.intelligence.models import CaseData, EntityData, RelData
from app.intelligence.temporal import emerging_bridges, network_evolution, split_at


def _make_case() -> CaseData:
    return CaseData(
        case_number="TEST",
        entities=[
            EntityData(id="A", type="PERSON", name="Alice"),
            EntityData(id="B", type="PERSON", name="Bob"),
            EntityData(id="C", type="PERSON", name="Carol"),
            EntityData(id="X", type="PERSON", name="Xander"),
        ],
        relationships=[
            # Cross-community link BEFORE the boundary
            RelData(source="A", target="B", rel_type="CALLED",
                    first_seen="2026-07-01T10:00", last_seen="2026-07-01T10:00", count=1),
            # Cross-community link AFTER the boundary
            RelData(source="A", target="C", rel_type="MESSAGED",
                    first_seen="2026-09-01T08:00", last_seen="2026-09-01T08:00", count=1),
            # Intra-community, before
            RelData(source="B", target="C", rel_type="CALLED",
                    first_seen="2026-06-15T09:00", last_seen="2026-06-15T09:00", count=1),
            # No timestamp — must not appear in either set
            RelData(source="A", target="X", rel_type="CALLED",
                    first_seen="", last_seen="", count=1),
        ],
    )


BOUNDARY = "2026-08-01T00:00"


class TestTemporalBoundary:
    def test_split_before_and_after_sets(self):
        data = _make_case()
        before, after = split_at(data, BOUNDARY)
        assert ("A", "B", "CALLED") in before
        assert ("A", "C", "MESSAGED") in after
        assert ("B", "C", "CALLED") in before
        # Untimed relationship must appear in neither set when boundary is present
        assert ("A", "X", "CALLED") not in before
        assert ("A", "X", "CALLED") not in after

    def test_split_no_boundary(self):
        data = _make_case()
        before, after = split_at(data, "")
        assert ("A", "B", "CALLED") in before
        assert ("A", "X", "CALLED") in before
        assert len(after) == 0

    def test_emerging_bridge_excludes_before_relationships(self):
        data = _make_case()
        communities = [["A", "B"], ["C", "X"]]
        # A-B (CALLED) is before boundary — must NOT be an emerging bridge
        bridges = emerging_bridges(data, communities, BOUNDARY)
        affected_nodes = {b.source for b in bridges}
        assert "A" in affected_nodes  # A gained A→C after boundary (cross-community)
        # A→B before boundary should NOT contribute; it's in the BEFORE set
        a_bridge = next(b for b in bridges if b.source == "A")
        assert a_bridge.after == 1.0  # only A→C, not A→B

    def test_network_evolution_new_rel_after_boundary(self):
        data = _make_case()
        changes = network_evolution(data, BOUNDARY)
        kinds = {c.kind for c in changes}
        assert "NEW_REL" in kinds
        new_sources = {c.source for c in changes if c.kind == "NEW_REL"}
        assert "A" in new_sources

    def test_relationship_trends_uses_first_seen(self):
        data = _make_case()
        trends = network_evolution(data, BOUNDARY)
        # Only A-C appears as new; it's in AFTER
        assert any(c.source == "A" and c.target == "C" for c in trends)

    def test_missing_timestamp_does_not_corrupt_boundary(self):
        """An untimed relationship must not end up in the after set."""
        data = CaseData(
            case_number="TEST",
            entities=[EntityData(id="P1", type="PERSON"), EntityData(id="P2", type="PERSON")],
            relationships=[
                RelData(source="P1", target="P2", rel_type="CALLED",
                        first_seen="", last_seen="", count=1),
            ],
        )
        before, after = split_at(data, "2026-09-01T00:00")
        assert len(before) == 0
        assert len(after) == 0
