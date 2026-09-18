"""P0.2: evidence coverage must be a real metric, never n/n."""
from __future__ import annotations

from app.intelligence.dna import compute_dna, compute_evidence_coverage
from app.intelligence.models import CaseData, EntityData, Evidence, RelData


def _case_with_partial_coverage() -> CaseData:
    return CaseData(
        case_number="TEST",
        entities=[
            EntityData(id="P-1", type="PERSON", name="Alice", source_ids=["CDR-001"]),
            EntityData(id="P-2", type="PERSON", name="Bob", source_ids=["FIR-001"]),
            EntityData(id="P-3", type="PERSON", name="Carol"),   # no source ref at all
            EntityData(id="P-4", type="PERSON", name="Dave", source_ids=["SOC-001"]),
        ],
        relationships=[
            RelData(source="P-1", target="P-2", rel_type="CALLED", count=1),
            RelData(source="P-3", target="P-4", rel_type="CALLED", count=1),
        ],
        evidence=[
            Evidence(id="E1", source_type="CDR", source_id="CDR-001", entity_ids=["P-2", "P-1"]),
            Evidence(id="E2", source_type="FIR", source_id="FIR-001", entity_ids=["P-2"]),
        ],
    )


class TestEvidenceCoverage:
    def test_partial_coverage_is_mean_of_per_entity_scores(self):
        d = _case_with_partial_coverage()
        # P-1,P-2 fully covered by evidence records; P-4 weak (source_ids only);
        # P-3 uncovered -> (1 + 1 + 0 + 0.5) / 4 = 62.5
        assert compute_evidence_coverage(d) == 62.5

    def test_empty_case_returns_zero_not_nan(self):
        d = CaseData(case_number="T")
        assert compute_evidence_coverage(d) == 0.0

    def test_compute_dna_uses_real_coverage(self):
        d = _case_with_partial_coverage()
        import networkx as nx
        g = nx.Graph()
        for e in d.entities:
            g.add_node(e.id)
        for r in d.relationships:
            g.add_edge(r.source, r.target)
        dna = compute_dna(g, d)
        assert dna.evidence_coverage == 62.5

    def test_compute_dna_without_data_is_zero_not_nn(self):
        import networkx as nx
        g = nx.Graph()
        for i in range(5):
            g.add_node(str(i))
        dna = compute_dna(g, None)
        assert dna.evidence_coverage == 0.0