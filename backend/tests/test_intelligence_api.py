"""Intelligence API endpoint tests (Phase 15)."""
import pytest
from fastapi.testclient import TestClient

ADMIN = "admin"
PW = "admin-secret"


@pytest.fixture()
def ctx(db_client: TestClient):
    resp = db_client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    case = db_client.post("/api/v1/cases", json={"title": "Intelligence Case", "priority": "HIGH"}, headers=auth)
    cn = case.json()["case_number"]
    # Ingest a small CDR + transaction to seed entities/relationships.
    client = db_client

    def upload(name, stype, content):
        r = client.post(f"/api/v1/cases/{cn}/sources/upload", headers=auth,
                        files={"file": (name, content.encode(), "text/csv")}, data={"source_type": stype})
        assert r.status_code == 201, r.text
        client.post(f"/api/v1/cases/{cn}/sources/{r.json()['source_id']}/process", headers=auth)

    upload("cdr.csv", "CDR",
           "caller,receiver,time\nN-1,N-2,2026-08-14T09:12\nN-2,N-1,2026-08-14T09:18\nN-1,N-3,2026-08-14T10:45\n")
    upload("txn.csv", "TRANSACTION",
           "sender,receiver,amount,time\nA-100,A-200,100000,2026-08-14T10:00\nA-200,A-100,15000,2026-08-15T11:00\n")
    return {"auth": auth, "client": client, "cn": cn}


def test_intelligence_object(ctx) -> None:
    r = ctx["client"].get(f"/api/v1/cases/{ctx['cn']}/intelligence", headers=ctx["auth"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "network_dna" in body
    assert "potential_links" in body
    assert "anomalies" in body
    assert "recommendations" in body
    assert body["evidence_gaps"] is not None


def test_hidden_links_endpoint(ctx) -> None:
    r = ctx["client"].get(f"/api/v1/cases/{ctx['cn']}/hidden-links", headers=ctx["auth"])
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_network_dna_endpoint(ctx) -> None:
    r = ctx["client"].get(f"/api/v1/cases/{ctx['cn']}/network-dna", headers=ctx["auth"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "density" in body
    assert "community_count" in body


def test_simulate_endpoint(ctx) -> None:
    payload = {"operation": "remove_entity", "subject": "N-1"}
    r = ctx["client"].post(f"/api/v1/cases/{ctx['cn']}/simulate", json=payload, headers=ctx["auth"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["operation"] == "remove_entity"
    assert "connectivity_change" in body


def test_leads_crud(ctx) -> None:
    client = ctx["client"]
    auth = ctx["auth"]
    lead = client.post(
        f"/api/v1/cases/{ctx['cn']}/leads",
        json={"title": "Potential link P-0421-P-0312", "priority": 40.0, "info_gain": 60.0,
              "entity_ids": ["N-1", "N-2"]},
        headers=auth,
    )
    assert lead.status_code == 201, lead.text
    lid = lead.json()["id"]

    # Canonical status model (P1-5): fresh hypothesis starts POTENTIAL.
    assert lead.json()["status"] == "POTENTIAL"

    # Only explicit analyst transitions reach ANALYST_CONFIRMED.
    patch = client.patch(
        f"/api/v1/cases/{ctx['cn']}/leads/{lid}",
        json={"status": "ANALYST_CONFIRMED"},
        headers=auth,
    )
    assert patch.status_code == 200
    assert patch.json()["status"] == "ANALYST_CONFIRMED"

    patch2 = client.patch(
        f"/api/v1/cases/{ctx['cn']}/leads/{lid}",
        json={"status": "REJECTED"},
        headers=auth,
    )
    assert patch2.status_code == 200
    assert patch2.json()["status"] == "REJECTED"

    # Legacy vocabulary is rejected by the canonical schema.
    legacy = client.patch(
        f"/api/v1/cases/{ctx['cn']}/leads/{lid}",
        json={"status": "DISMISSED"},
        headers=auth,
    )
    assert legacy.status_code == 422

    ls = client.get(f"/api/v1/cases/{ctx['cn']}/leads", headers=auth)
    assert ls.status_code == 200
    assert any(x["id"] == lid for x in ls.json())


def test_intelligence_requires_auth(ctx) -> None:
    assert ctx["client"].get(f"/api/v1/cases/{ctx['cn']}/intelligence").status_code == 401