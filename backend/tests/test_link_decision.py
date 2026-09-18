"""P1.3: analyst confirm/reject/defer workflow stores decision + audit."""
import pytest
from fastapi.testclient import TestClient

ADMIN = "admin"
PW = "admin-secret"


@pytest.fixture()
def ctx(db_client: TestClient):
    resp = db_client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    assert resp.status_code == 200
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    case = db_client.post("/api/v1/cases", json={"title": "Decision Case", "priority": "HIGH"}, headers=auth)
    assert case.status_code == 201
    return {"auth": auth, "client": db_client, "case_number": case.json()["case_number"]}


class TestLinkDecision:
    def test_confirm_stores_status_and_audit(self, ctx):
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]
        r = client.post(
            f"/api/v1/cases/{case_number}/potential-links/decision",
            json={"source": "P-0421", "target": "P-0312", "decision": "CONFIRM",
                  "evidence_ids": ["FIR-001"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["new_status"] == "ANALYST_CONFIRMED"
        assert body["previous_status"] == "POTENTIAL"
        assert body["decision"] == "CONFIRM"

        # Audit trail recorded.
        audit = client.get("/api/v1/audit?limit=20", headers=auth)
        actions = [a["action"] for a in audit.json()]
        assert "potential_link_confirm" in actions

        # Rejecting afterwards rewrites the latest status from the previous one.
        r2 = client.post(
            f"/api/v1/cases/{case_number}/potential-links/decision",
            json={"source": "P-0312", "target": "P-0421", "decision": "REJECT"},
            headers=auth,
        )
        assert r2.json()["new_status"] == "REJECTED"
        assert r2.json()["previous_status"] == "ANALYST_CONFIRMED"

        # Pair key normalized regardless of argument order.
        decisions = client.get(f"/api/v1/cases/{case_number}/potential-links/decisions", headers=auth)
        assert decisions.status_code == 200
        assert len(decisions.json()) == 1

    def test_defer_keeps_potential(self, ctx):
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]
        r = client.post(
            f"/api/v1/cases/{case_number}/potential-links/decision",
            json={"source": "N-4821", "target": "N-9044", "decision": "DEFER", "notes": "wait for CDR"},
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["new_status"] == "DEFERRED"

    def test_decision_invalidates_intelligence_cache(self, ctx):
        # First fetch builds the cache; a decision must invalidate it.
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]
        before = client.get(f"/api/v1/cases/{case_number}/intelligence", headers=auth)
        assert before.status_code == 200
        assert "link_decisions" in before.json()
        r = client.post(
            f"/api/v1/cases/{case_number}/potential-links/decision",
            json={"source": "P-0421", "target": "P-0312", "decision": "CONFIRM"},
            headers=auth,
        )
        assert r.status_code == 200
        after = client.get(f"/api/v1/cases/{case_number}/intelligence", headers=auth)
        assert "<->".join(sorted(["P-0421", "P-0312"])) in after.json()["link_decisions"]

    def test_invalid_decision_rejected(self, ctx):
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]
        r = client.post(
            f"/api/v1/cases/{case_number}/potential-links/decision",
            json={"source": "P-0421", "target": "P-0312", "decision": "MAYBE"},
            headers=auth,
        )
        assert r.status_code == 422