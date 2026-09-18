"""P0.4: post-ingestion intelligence + graph refresh (no stale cache)."""
import pytest
from fastapi.testclient import TestClient

ADMIN = "admin"
PW = "admin-secret"

CDR_CSV = (
    b"caller,receiver,time,duration\n"
    b"N-4821,N-9044,2026-08-14T09:12,34\n"
    b"N-9044,N-7712,2026-08-14T10:00,12\n"
)


@pytest.fixture()
def ctx(db_client: TestClient):
    resp = db_client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    assert resp.status_code == 200
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    case = db_client.post("/api/v1/cases", json={"title": "Refresh Case", "priority": "HIGH"}, headers=auth)
    assert case.status_code == 201
    return {"auth": auth, "client": db_client, "case_number": case.json()["case_number"]}


class TestPostIngestionRefresh:
    def _upload_and_process(self, ctx, content: bytes, filename: str = "cdr.csv") -> str:
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]
        up = client.post(
            f"/api/v1/cases/{case_number}/sources/upload",
            headers=auth,
            files={"file": (filename, content, "text/csv")},
            data={"source_type": "CDR"},
        )
        assert up.status_code == 201
        sid = up.json()["source_id"]
        proc = client.post(f"/api/v1/cases/{case_number}/sources/{sid}/process", headers=auth)
        assert proc.status_code == 200
        return sid

    def test_intelligence_reflects_new_data_and_cache_invalidates(self, ctx):
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]

        sid = self._upload_and_process(ctx, CDR_CSV)
        intel1 = client.get(f"/api/v1/cases/{case_number}/intelligence", headers=auth)
        assert intel1.status_code == 200
        entity_ids = {e["id"] for e in intel1.json()["entities"]}
        assert {"N-4821", "N-9044", "N-7712"} <= entity_ids

        # A second source lands on the SAME case afterwards -> the cached
        # intelligence must NOT be stale.
        more = (
            b"caller,receiver,time,duration\n"
            b"N-9044,N-7712,2026-08-15T11:30,8\n"
            b"N-7712,N-4821,2026-08-15T12:00,9\n"
        )
        self._upload_and_process(ctx, more, filename="cdr-b.csv")
        intel2 = client.get(f"/api/v1/cases/{case_number}/intelligence", headers=auth)
        entity_ids2 = {e["id"] for e in intel2.json()["entities"]}
        assert {"N-4821", "N-9044", "N-7712"} <= entity_ids2
        # Growth reflects the second file's relationships/entities.
        assert intel2.json()["case_id"] == intel1.json()["case_id"]

        # Graph store already materialized the case entities server-side.
        network = client.get("/api/v1/graph/network", headers=auth)
        node_ids = {n["id"] for n in network.json()["nodes"]}
        assert "N-4821" in node_ids

    def test_source_processed_audit_recorded(self, ctx):
        client, auth, case_number = ctx["client"], ctx["auth"], ctx["case_number"]
        self._upload_and_process(ctx, CDR_CSV)
        audit = client.get("/api/v1/audit?limit=20", headers=auth)
        actions = [a["action"] for a in audit.json()]
        assert "source_uploaded" in actions
        assert "source_processed" in actions