"""Final engineering hardening pass tests.

Covers: case-scoped graph, emerging-bridge integration, invalid/timezone
timestamps, record-level provenance, assistant no-live->demo fallback,
case-scoped location anomalies, unified intelligence contract, status
consistency and what-if isolation.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.intelligence.models import CaseData, EntityData, RelData

ADMIN = "admin"
PW = "admin-secret"


@pytest.fixture()
def ctx(db_client: TestClient):
    resp = db_client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    assert resp.status_code == 200
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    case = db_client.post("/api/v1/cases", json={"title": "Harden Case A", "priority": "HIGH"}, headers=auth)
    assert case.status_code == 201
    case_b = db_client.post("/api/v1/cases", json={"title": "Harden Case B", "priority": "MEDIUM"}, headers=auth)
    assert case_b.status_code == 201
    return {"auth": auth, "client": db_client, "cn": case.json()["case_number"], "cn_b": case_b.json()["case_number"]}


def _ingest_cdr(client: TestClient, auth: dict, case_number: str, filename: str, content: bytes) -> str:
    up = client.post(
        f"/api/v1/cases/{case_number}/sources/upload",
        headers=auth,
        files={"file": (filename, content, "text/csv")},
        data={"source_type": "CDR"},
    )
    assert up.status_code == 201, up.text
    sid = up.json()["source_id"]
    proc = client.post(f"/api/v1/cases/{case_number}/sources/{sid}/process", headers=auth)
    assert proc.status_code == 200, proc.text
    assert proc.json()["metrics"].get("graph_refreshed") is True
    return sid


CDR_A = (
    b"caller,receiver,time,duration\n"
    b"N-1111,N-2222,2026-08-14T09:12,34\n"
    b"N-2222,N-3333,2026-08-14T10:00,12\n"
)
CDR_B = (
    b"caller,receiver,time,duration\n"
    b"P-7777,P-8888,2026-08-14T09:12,34\n"
    b"P-8888,P-9999,2026-08-14T10:00,12\n"
)


class TestCaseScopedGraph:
    def test_case_graph_only_contains_own_case(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)
        _ingest_cdr(client, auth, ctx["cn_b"], "b.csv", CDR_B)

        ga = client.get(f"/api/v1/cases/{ctx['cn']}/graph", headers=auth)
        assert ga.status_code == 200
        node_ids = {n["id"] for n in ga.json()["nodes"]}
        assert {"N-1111", "N-2222", "N-3333"} <= node_ids
        assert "P-7777" not in node_ids  # other case's data must NOT leak

        gb = client.get(f"/api/v1/cases/{ctx['cn_b']}/graph", headers=auth)
        gb_ids = {n["id"] for n in gb.json()["nodes"]}
        assert "P-7777" in gb_ids
        assert "N-1111" not in gb_ids

    def test_case_graph_missing_case_404(self, ctx):
        r = ctx["client"].get("/api/v1/cases/CASE-NOPE/graph", headers=ctx["auth"])
        assert r.status_code == 404


class TestUnifiedIntelligenceContract:
    def test_intelligence_has_full_contract(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)
        intel = client.get(f"/api/v1/cases/{ctx['cn']}/intelligence", headers=auth).json()
        for key in ("case_id", "entities", "relationships", "evidence", "evidence_fusion",
                    "relationship_fusion", "temporal_changes", "anomalies", "potential_links",
                    "link_decisions", "evidence_gaps", "network_dna", "entity_priorities",
                    "relationship_priorities", "information_gain", "recommendations"):
            assert key in intel, f"missing {key}"
        ids = {e["id"] for e in intel["entities"]}
        assert {"N-1111", "N-2222", "N-3333"} <= ids


class TestEmergingBridgeIntegration:
    def _clique_case(self, cross_after: bool = True, cross_ts: str = "2026-09-02T10:00", connect: bool = True) -> CaseData:
        # Six observations with the connecting edge LAST so that
        # default_boundary (P75) falls BEFORE the cross edge when it is "after".
        rels = [
            RelData(source="A", target="B", rel_type="CALLED",
                    first_seen="2026-06-01T08:00", last_seen="2026-06-01T08:00", count=1),
            RelData(source="C", target="D", rel_type="CALLED",
                    first_seen="2026-06-02T08:00", last_seen="2026-06-02T08:00", count=1),
            RelData(source="A", target="B", rel_type="CALLED",
                    first_seen="2026-06-15T09:00", last_seen="2026-06-15T09:00", count=1),
            RelData(source="C", target="D", rel_type="CALLED",
                    first_seen="2026-06-20T09:00", last_seen="2026-06-20T09:00", count=1),
            RelData(source="A", target="B", rel_type="CALLED",
                    first_seen="2026-09-01T08:00", last_seen="2026-09-01T08:00", count=1),
        ]
        if connect:
            rels.append(RelData(source="B", target="C", rel_type="CALLED",
                                first_seen=cross_ts, last_seen=cross_ts, count=1))
        return CaseData(
            case_number="BRIDGE",
            entities=[EntityData(id=n, type="PERSON") for n in ("A", "B", "C", "D")],
            relationships=rels,
        )

    def _kinds(self, data: CaseData) -> list[str]:
        from app.services.case_intelligence_service import compute_from_data
        return [c["kind"] for c in compute_from_data(-1, data)["temporal_changes"]]

    def test_new_cross_community_after_boundary_is_emerging(self):
        assert "EMERGING_BRIDGE" in self._kinds(self._clique_case())

    def test_cross_community_edge_before_boundary_is_not_emerging(self):
        # The only connecting edge existed BEFORE the split point.
        assert "EMERGING_BRIDGE" not in self._kinds(
            self._clique_case(cross_ts="2026-07-01T08:00")
        )

    def test_invalid_timestamp_creates_no_false_bridge(self):
        assert "EMERGING_BRIDGE" not in self._kinds(
            self._clique_case(cross_ts="garbage-date", connect=True)
        )

    def test_missing_timestamp_creates_no_false_bridge(self):
        assert "EMERGING_BRIDGE" not in self._kinds(
            self._clique_case(cross_ts="", connect=True)
        )

    def test_timezone_aware_timestamps_respected(self):
        # +05:30 on 2026-09-02 10:00 == 04:30 UTC, still AFTER an 08-01 boundary.
        kinds_after = self._kinds(self._clique_case(cross_ts="2026-09-02T10:00+05:30"))
        assert "EMERGING_BRIDGE" in kinds_after
        # +05:30 on 2026-07-01 23:00 == 17:30 UTC, still BEFORE an 08-01 boundary.
        kinds_before = self._kinds(self._clique_case(cross_ts="2026-07-01T23:00+05:30"))
        assert "EMERGING_BRIDGE" not in kinds_before


class TestRecordLevelProvenance:
    def test_text_source_evidence_carries_record_and_entity_ids(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        fire_text = (
            "On 2026-09-02, Ramesh Verma used vehicle MH-02-AB-7890. "
            "Contact phone 9811111111 was observed at Sector 17 warehouse."
        )
        up = client.post(
            f"/api/v1/cases/{ctx['cn']}/sources/upload",
            headers=auth,
            files={"file": ("fir.txt", fire_text.encode(), "text/plain")},
            data={"source_type": "FIR"},
        )
        assert up.status_code == 201
        sid = up.json()["source_id"]
        proc = client.post(f"/api/v1/cases/{ctx['cn']}/sources/{sid}/process", headers=auth)
        assert proc.status_code == 200, proc.text

        intel = client.get(f"/api/v1/cases/{ctx['cn']}/intelligence", headers=auth).json()
        evidence = intel["evidence"]
        assert evidence, "text source must produce evidence"
        has_record = any(e.get("record_id") for e in evidence)
        assert has_record, "evidence must link to the originating record"
        has_entity_refs = any(e.get("entity_ids") for e in evidence)
        assert has_entity_refs, "text-extracted evidence must name its entity ids"
        # The provenance must actually reference extracted entities.
        entity_ids = {e["id"] for e in intel["entities"]}
        assert any(any(rid in entity_ids for rid in e["entity_ids"]) for e in evidence)

    def test_record_field_evidence_has_record_id(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)
        intel = client.get(f"/api/v1/cases/{ctx['cn']}/intelligence", headers=auth).json()
        evidence = intel["evidence"]
        assert evidence
        assert all(e.get("record_id") for e in evidence), "every CDR record evidence must carry record_id"


class TestAssistantNoLiveToDemoFallback:
    def test_nonexistent_case_returns_explicit_not_found(self, ctx):
        r = ctx["client"].post(
            "/api/v1/analysis/assistant",
            json={"question": "case overview", "case_key": "CASE-DOES-NOT-EXIST"},
            headers=ctx["auth"],
        )
        assert r.status_code == 200
        body = r.json()
        assert body["found"] is False
        assert "Case not found" in body["answer"]
        assert body["structured"] is None or body["structured"]["found"] is False

    def test_live_case_never_leaks_demo_entities(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        # Existing but EMPTY case -> demo entities must NOT appear.
        r = client.post(
            "/api/v1/analysis/assistant",
            json={"question": "who is P-0421", "case_key": ctx["cn"]},
            headers=auth,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["found"] is False
        assert "P-0421" in body["answer"]  # explicit: no supporting evidence in this case

    def test_live_case_answers_from_persisted_data(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)
        r = client.post(
            "/api/v1/analysis/assistant",
            json={"question": "show connections of N-1111", "case_key": ctx["cn"]},
            headers=auth,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["found"] is True
        entities = body["structured"]["entities"]
        assert any(e["id"] == "N-1111" for e in entities)
        # Answer references the persisted source's evidence, not demo ids.
        assert body["structured"]["source_ids"], "persisted case must supply source evidence"
        assert not any("DEMO" in s or "NETWORK" in s for s in body["structured"]["source_ids"])


class TestCaseScopedLocations:
    def test_location_anomaly_uses_case_data_not_offline_map(self):
        data = CaseData(
            case_number="LOC",
            entities=[
                EntityData(id="P-1", type="PERSON"),
                EntityData(id="L-X", type="LOCATION", name="Warehouse 4"),
            ],
            relationships=[
                RelData(source="P-1", target="L-X", rel_type="USES",
                        first_seen="2026-08-01T08:00", last_seen="2026-08-02T08:00", count=3),
            ],
        )
        from app.services.case_intelligence_service import compute_from_data
        intel = compute_from_data(-1, data)
        kinds = {a["kind"] for a in intel["anomalies"]}
        # Location-derived observations flow through the case-scoped builder.
        assert any(a["entity_id"] == "Warehouse 4" for a in intel["anomalies"])
        assert "LOCATION" in kinds


class TestReportCaseScoping:
    def test_investigation_report_has_case_intelligence_sections(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)
        r = client.post(
            "/api/v1/reports/generate",
            json={"report_type": "investigation_summary", "case_number": ctx["cn"]},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        headings = {s["heading"] for s in r.json()["sections"]}
        assert "Case Overview" in headings
        assert "Network Structure" in headings  # from case intelligence sections
        assert "Analytical Caveats" in headings
        assert "N-1111" in str(r.json()["sections"])


class TestAuditCoverage:
    def test_ingestion_graph_decision_simulation_report_audited(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        sid = _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)

        # Configuration audit breadcrumbs are exercised through the mutations.
        client.post(
            f"/api/v1/cases/{ctx['cn']}/potential-links/decision",
            json={"source": "N-1111", "target": "P-0421", "decision": "DEFER"},
            headers=auth,
        )
        client.post(
            f"/api/v1/cases/{ctx['cn']}/simulate",
            json={"operation": "hide_entity", "subject": "N-1111"},
            headers=auth,
        )
        client.post(
            "/api/v1/reports/generate",
            json={"report_type": "network_analysis"},
            headers=auth,
        )
        # Exclude the existing audit fixture writes; only assert our events exist.
        audit = client.get("/api/v1/audit?limit=50", headers=auth).json()
        actions = {a["action"] for a in audit}
        assert "source_uploaded" in actions
        assert "source_processed" in actions
        assert "potential_link_defer" in actions
        assert "simulation_executed" in actions
        assert "report_generated" in actions


class TestStatusModel:
    def test_link_decision_statuses_are_canonical(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        up = client.post(
            f"/api/v1/cases/{ctx['cn']}/potential-links/decision",
            json={"source": "N-1111", "target": "N-2222", "decision": "CONFIRM"},
            headers=auth,
        )
        assert up.status_code == 200
        assert up.json()["new_status"] == "ANALYST_CONFIRMED"
        assert up.json()["previous_status"] == "POTENTIAL"
        for verb, status in (("REJECT", "REJECTED"), ("DEFER", "DEFERRED")):
            r = client.post(
                f"/api/v1/cases/{ctx['cn']}/potential-links/decision",
                json={"source": "N-1111", "target": "N-2222", "decision": verb},
                headers=auth,
            )
            assert r.status_code == 200
            assert r.json()["new_status"] == status

    def test_legacy_decision_verb_rejected(self, ctx):
        r = ctx["client"].post(
            f"/api/v1/cases/{ctx['cn']}/potential-links/decision",
            json={"source": "N-1", "target": "N-2", "decision": "ACCEPT"},
            headers=ctx["auth"],
        )
        assert r.status_code == 422

    def test_lead_statuses_use_canonical_vocabulary(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        lead = client.post(
            f"/api/v1/cases/{ctx['cn']}/leads",
            json={"title": "Hypothesis", "priority": 30.0},
            headers=auth,
        )
        assert lead.status_code == 201
        assert lead.json()["status"] == "POTENTIAL"
        legacy = client.patch(
            f"/api/v1/cases/{ctx['cn']}/leads/{lead.json()['id']}",
            json={"status": "DISMISSED"},
            headers=auth,
        )
        assert legacy.status_code == 422


class TestWhatIfIsolation:
    def test_simulation_never_mutates_source_graph(self, ctx):
        client, auth = ctx["client"], ctx["auth"]
        _ingest_cdr(client, auth, ctx["cn"], "a.csv", CDR_A)
        before = client.get(f"/api/v1/cases/{ctx['cn']}/graph", headers=auth).json()
        r = client.post(
            f"/api/v1/cases/{ctx['cn']}/simulate",
            json={"operation": "remove_entity", "subject": "N-1111"},
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["after_nodes"] < r.json()["before_nodes"]
        after = client.get(f"/api/v1/cases/{ctx['cn']}/graph", headers=auth).json()
        assert {n["id"] for n in before["nodes"]} == {n["id"] for n in after["nodes"]}


class TestXlsxIntake:
    def test_xlsx_parse_when_openpyxl_available(self, ctx):
        try:
            import openpyxl  # noqa: F401
        except ImportError:  # pragma: no cover - environment dependent
            pytest.skip("openpyxl not installed")
        import io

        from app.ingestion.parsers import parse_source

        workbook = None
        content = _build_xlsx_bytes()
        parsed = parse_source("records.xlsx", content, "CDR")
        assert parsed.error is None, parsed.error
        assert parsed.format == "XLSX"
        assert parsed.records, "XLSX must yield canonical records"


def _build_xlsx_bytes() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["caller", "receiver", "time", "duration"])
    ws.append(["N-5000", "N-6000", "2026-08-14T09:12", "34"])
    ws.append(["N-6000", "N-7000", "2026-08-14T10:00", "12"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()