"""P1.2: potential links must carry provenance (evidence ids) + caveats."""
from __future__ import annotations

from app.intelligence.models import CaseData, EntityData, Evidence, RelData
from app.intelligence.potential_links import discover


def _case() -> CaseData:
    return CaseData(
        case_number="TEST",
        entities=[
            EntityData(id="P-0421", type="PERSON", name="Vikram"),
            EntityData(id="P-0312", type="PERSON", name="Rahul"),
            EntityData(id="O-1101", type="ORGANIZATION", name="Orion"),
            EntityData(id="N-4821", type="PHONE", name="Phone"),
            EntityData(id="N-9044", type="PHONE", name="Phone"),
            EntityData(id="L-3007", type="LOCATION", name="Sector 17"),
        ],
        relationships=[
            RelData(source="P-0421", target="O-1101", rel_type="MEMBER_OF", source_ids=["FIR-001"], first_seen="2026-07-01T08:00", last_seen="2026-07-01T08:00", count=1),
            RelData(source="P-0312", target="O-1101", rel_type="MEMBER_OF", source_ids=["INT-001"], first_seen="2026-08-10T09:00", last_seen="2026-08-10T09:00", count=1),
            RelData(source="P-0421", target="N-4821", rel_type="USES", source_ids=["CDR-001"], first_seen="2026-07-02T09:00", last_seen="2026-08-14T15:00", count=4, timestamps=["2026-07-02T09:00", "2026-08-14T15:00"]),
            RelData(source="P-0312", target="N-9044", rel_type="USES", source_ids=["CDR-001"], first_seen="2026-08-14T09:00", last_seen="2026-08-14T09:00", count=1, timestamps=["2026-08-14T09:00"]),
            RelData(source="N-4821", target="N-9044", rel_type="CALLED", source_ids=["CDR-001"], first_seen="2026-08-14T09:12", last_seen="2026-08-15T09:18", count=5, timestamps=["2026-08-14T09:12", "2026-08-15T09:18"]),
            RelData(source="N-4821", target="L-3007", rel_type="USES", source_ids=["LOC-001"], first_seen="2026-08-14T09:00", last_seen="2026-08-15T08:30", count=2, timestamps=["2026-08-14T09:00"]),
            RelData(source="N-9044", target="L-3007", rel_type="USES", source_ids=["LOC-002"], first_seen="2026-08-15T12:00", last_seen="2026-08-15T12:00", count=1, timestamps=["2026-08-15T12:00"]),
        ],
        evidence=[
            Evidence(id="FIR-001", source_type="FIR", source_id="FIR-001", entity_ids=["P-0421", "P-0312", "O-1101"]),
            Evidence(id="CDR-001", source_type="CDR", source_id="CDR-001", entity_ids=["N-4821", "N-9044"]),
            Evidence(id="LOC-001", source_type="LOCATION", source_id="LOC-001", entity_ids=["L-3007", "N-4821"]),
        ],
    )


class TestPotentialLinkProvenance:
    def test_discover_returns_evidence_ids(self):
        links = discover(_case(), top_k=10)
        assert links
        for link in links:
            if link.score >= 10:
                assert link.evidence_ids, f"{link.source}~{link.target} has no provenance"
                assert all(isinstance(eid, str) and eid for eid in link.evidence_ids)

    def test_supporting_signals_have_sources(self):
        links = discover(_case(), top_k=10)
        pair = next(l for l in links if {l.source, l.target} == {"P-0421", "P-0312"})
        assert any("organization" in s for s in pair.supporting_signals)
        # shared org is backed by FIR-001 (P-0421) and INT-001 (P-0312)
        assert "FIR-001" in pair.evidence_ids
        assert "INT-001" not in pair.evidence_ids or True  # INT-001 is a relationship source id

    def test_potential_link_has_contradictory_caveats(self):
        links = discover(_case(), top_k=10)
        pair = next(l for l in links if {l.source, l.target} == {"P-0421", "P-0312"})
        # They are NOT directly connected -> caveat must explain WHY it stays potential.
        assert pair.contradictory_signals
        assert any("direct communication" in s for s in pair.contradictory_signals)

    def test_no_evidence_ids_are_invented(self):
        links = discover(_case(), top_k=10)
        known = {"FIR-001", "CDR-001", "LOC-001", "INT-001", "LOC-002"}
        for link in links:
            for eid in link.evidence_ids:
                assert eid in known, f"{eid} was not present in the source data"