"""Blockchain / evidence integrity tests (Phases 27-28).

Covers: deterministic hashing, canonical JSON, Merkle roots, genesis,
chaining, tamper detection (block/previous-hash/evidence/intelligence/report),
evidence versioning, record verification, outbox failure behavior, case
isolation, RBAC and API response contracts.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.blockchain.hashes import (
    canonical_json,
    hash_decision_payload,
    hash_evidence_payload,
    hash_intelligence_snapshot,
    hash_json,
    hash_report_payload,
    hash_text,
    report_integrity_payload,
)
from app.blockchain.local_ledger import LocalPermissionedLedger
from app.blockchain.merkle import batch_integrity, merkle_root
from app.core.database import Base
from app.models.case import Case, CasePriority, CaseStatus
from app.models.integrity import EvidenceIntegrity, IntegrityOutbox, LedgerBlock, LedgerEvent
from app.models.source import Source

ADMIN = "admin"
PW = "admin-secret"


# ---------------------------------------------------------------------------
# Pure engine / hashing unit tests
# ---------------------------------------------------------------------------

class TestHashing:
    def test_hash_text_deterministic(self):
        assert hash_text("alpha") == hash_text("alpha")
        assert len(hash_text("alpha")) == 64

    def test_canonical_json_ignores_key_order(self):
        a = canonical_json({"b": 1, "a": [1, 2]})
        b = canonical_json({"a": [1, 2], "b": 1})
        assert a == b
        assert hash_json({"b": 1, "a": [1, 2]}) == hash_json({"a": [1, 2], "b": 1})

    def test_decisions_and_snapshots_deterministic(self):
        d1 = hash_decision_payload(case_id=1, entity_a="A", entity_b="B", decision="CONFIRM",
                                   evidence_ids_hash="H", notes_hash="N", analyst_id=1)
        d2 = hash_decision_payload(case_id=1, entity_a="A", entity_b="B", decision="CONFIRM",
                                   evidence_ids_hash="H", notes_hash="N", analyst_id=1)
        assert hash_json(d1) == hash_json(d2)


class TestMerkle:
    def test_root_deterministic(self):
        hashes = ["H1", "H2", "H3", "H4"]
        assert merkle_root(hashes) == merkle_root(list(reversed(hashes)))

    def test_odd_count_uses_pair_with_self(self):
        root = merkle_root(["A", "B", "C"])
        assert root and len(root) == 64

    def test_empty_returns_none(self):
        assert merkle_root([]) is None

    def test_batch_integrity(self):
        info = batch_integrity(["A", "B"])
        assert info["algorithm"] == "MERKLE-SHA256"
        assert info["record_count"] == 2
        assert info["merkle_root"]


class TestLocalLedger:
    def _engine(self):
        return LocalPermissionedLedger()

    def test_genesis_block(self):
        engine = self._engine()
        block = engine.compute_block(previous=None, case_id="1", events=[{"hash": "H"}])
        assert block.index == 0
        assert block.previous_hash == "0" * 64
        assert block.hash and len(block.hash) == 64

    def test_chaining_and_validation(self):
        engine = self._engine()
        b0 = engine.compute_block(previous=None, case_id="1", events=[{"hash": "H0"}])
        b1 = engine.compute_block(previous=b0, case_id="1", events=[{"hash": "H1"}])
        b2 = engine.compute_block(previous=b1, case_id="1", events=[{"hash": "H2"}])
        assert [b.index for b in (b0, b1, b2)] == [0, 1, 2]
        assert b1.previous_hash == b0.hash
        assert b2.previous_hash == b1.hash
        verification = engine.verify_chain([b0, b1, b2], engine.genesis_params("1"))
        assert verification.chain_valid is True
        assert verification.blocks == 3

    def test_tampered_block_hash_detected(self):
        engine = self._engine()
        b0 = engine.compute_block(previous=None, case_id="1", events=[{"hash": "H0"}])
        b1 = engine.compute_block(previous=b0, case_id="1", events=[{"hash": "H1"}])
        b1.hash = "F" * 64  # tamper
        verification = engine.verify_chain([b0, b1], engine.genesis_params("1"))
        assert verification.chain_valid is False
        assert verification.block_hashes_valid is False
        assert any("hash mismatch" in issue for issue in verification.issues)

    def test_tampered_previous_hash_detected(self):
        engine = self._engine()
        b0 = engine.compute_block(previous=None, case_id="1", events=[{"hash": "H0"}])
        b1 = engine.compute_block(previous=b0, case_id="1", events=[{"hash": "H1"}])
        b2 = engine.compute_block(previous=b1, case_id="1", events=[{"hash": "H2"}])
        b2.previous_hash = "E" * 64  # breaks chain link
        verification = engine.verify_chain([b0, b1, b2], engine.genesis_params("1"))
        assert verification.chain_valid is False
        assert verification.previous_hashes_valid is False

    def test_tampered_data_hash_detected(self):
        engine = self._engine()
        b0 = engine.compute_block(previous=None, case_id="1", events=[{"hash": "H0"}])
        b1 = engine.compute_block(previous=b0, case_id="1", events=[{"hash": "H1"}])
        b1.data_hash = "D" * 64
        verification = engine.verify_chain([b0, b1], engine.genesis_params("1"))
        assert verification.chain_valid is False

    def test_events_enter_block_reference(self):
        engine = self._engine()
        block = engine.compute_block(previous=None, case_id="1",
                                     events=[{"transaction_id": "TX-1", "event_type": "EVIDENCE_REGISTERED",
                                              "entity_type": "source", "entity_id": "SRC-1",
                                              "payload_hash": "PH", "hash": "PH"}])
        assert block.events[0]["transaction_id"] == "TX-1"


# ---------------------------------------------------------------------------
# Service-level (async, DB-backed)
# ---------------------------------------------------------------------------

@pytest.fixture()
async def integrity_ctx():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with S() as session:
        case = Case(case_number="CASE-INT-1", title="Integrity Case",
                    status=CaseStatus.OPEN.value, priority=CasePriority.HIGH.value)
        session.add(case)
        await session.flush()
        session.add(Source(case_id=case.id, source_id="SRC-1", filename="fir.txt",
                           file_type="TEXT", source_type="FIR", status="PROCESSED",
                           record_count=1, metadata_json={
                               "records": [{"id": "1", "timestamp": "2026-09-01T10:00",
                                            "text": "Ramesh Verma used vehicle MH-02-AB-7890.",
                                            "fields": {"entity": "Ramesh Verma"}}],
                               "text": "FIR text",
                           }))
        await session.commit()
        yield {"case_id": case.id, "case_number": case.case_number, "S": S}
    await engine.dispose()


class TestIntegrityService:
    async def test_register_evidence_creates_chain_and_event(self, integrity_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            content = hash_evidence_payload({"source_id": "SRC-1", "records": []})
            registered = await svc.register_evidence(
                case_id=case_id, source_id="SRC-1", source_type="FIR", filename="fir.txt",
                evidence_hash="A" * 64, content_hash=content, actor_id=None,
            )
            assert registered["status"] in ("REGISTERED", "PENDING")
            chain = await svc.get_case_ledger(case_id)
            assert chain, "a block must exist"
            assert chain[0]["index"] == 0
            events = await svc.get_events(case_id)
            assert any(e["event_type"] == "EVIDENCE_REGISTERED" for e in events)
            summary = await svc.case_summary(case_id)
            assert summary["chain_status"] == "VALID"
            assert summary["blocks"] >= 1
            assert summary["evidence_registered"] >= 1

    async def test_duplicate_content_does_not_create_version(self, integrity_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        content = hash_evidence_payload({"source_id": "SRC-1", "records": []})
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                        filename="fir.txt", evidence_hash="A" * 64,
                                        content_hash=content, actor_id=None)
            again = await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                                filename="fir.txt", evidence_hash="A" * 64,
                                                content_hash=content, actor_id=None)
            assert again["version"] == 1  # no new version for identical content

    async def test_changed_content_creates_version_and_event(self, integrity_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                        filename="fir.txt", evidence_hash="A" * 64,
                                        content_hash="H1", actor_id=None)
            v2 = await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                             filename="fir.txt", evidence_hash="B" * 64,
                                             content_hash="H2", actor_id=None)
            assert v2["version"] == 2
            history = await svc.get_evidence_history(case_id, "SRC-1")
            assert [e["version"] for e in history] == [1, 2]
            events = await svc.get_events(case_id)
            assert any(e["event_type"] == "EVIDENCE_VERSION_CREATED" for e in events)

    async def test_tampered_evidence_detected(self, integrity_ctx):
        from app.blockchain.hashes import canonical_evidence_payload
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        original_content = hash_evidence_payload(canonical_evidence_payload(
            case_id=case_id, source_id="SRC-1", source_type="FIR", filename="fir.txt",
            records=[{"id": "1", "timestamp": "2026-09-01T10:00",
                      "text": "Ramesh Verma used vehicle MH-02-AB-7890.",
                      "fields": {"entity": "Ramesh Verma"}}],
            text="FIR text"))
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                        filename="fir.txt", evidence_hash="A" * 64,
                                        content_hash=original_content, actor_id=None)
            # TAMPER: change the stored source payload.
            from app.repositories.source_repository import SourceRepository
            rows = await SourceRepository(session).list_by_case(int(case_id))
            source = next(r for r in rows if r.source_id == "SRC-1")
            source.metadata_json = {"records": [{"id": "1", "fields": {"entity": "CHANGED NAME"}}], "text": "tampered"}
            await SourceRepository(session).save(source)
            await session.commit()

            result = await svc.verify_evidence(case_id, "SRC-1")
            assert result["status"] == "MISMATCH"
            assert result["verified"] is False

    async def test_record_batch_and_record_verification(self, integrity_ctx):
        from app.blockchain.hashes import hash_record
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.source_repository import SourceRepository
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        records = [
            {"id": "1", "source_type": "FIR", "timestamp": "2026-09-01T10:00",
             "fields": {"entity": "Ramesh Verma"}},
            {"id": "2", "source_type": "FIR", "timestamp": "2026-09-01T11:00",
             "fields": {"entity": "Nihal Singh"}},
        ]
        async with S() as session:
            # Model the real pipeline: the stored source payload IS the batch.
            rows = await SourceRepository(session).list_by_case(int(case_id))
            source = next(r for r in rows if r.source_id == "SRC-1")
            source.metadata_json = {**source.metadata_json, "records": records}
            await SourceRepository(session).save(source)
            await session.commit()

            svc = BlockchainIntegrityService(session)
            await svc.register_processed_batch(case_id=case_id, source_id="SRC-1",
                                               source_type="FIR", records=records, actor_id=None)
            root = merkle_root([hash_record(r) for r in records])
            events = await svc.get_events(case_id)
            batch_event = next(e for e in events if e["event_type"] == "EVIDENCE_PROCESSED"
                               and e["payload_json"].get("merkle_root") == root)
            assert batch_event["block_index"] is not None
            result = await svc.verify_record(case_id, "SRC-1", "1")
            assert result["verified"] is True
            assert result["merkle_root"] == root

    async def test_decision_and_snapshot_and_report_events(self, integrity_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.record_analyst_decision(case_id=case_id, entity_a="P-1", entity_b="P-2",
                                              decision="CONFIRM", evidence_ids=["SRC-1"],
                                              notes="reviewed", actor_id=1)
            await svc.register_intelligence_snapshot(case_id=case_id,
                                                     snapshot={"case_id": case_id, "entities": [], "relationships": [],
                                                               "evidence": [], "anomalies": [],
                                                               "potential_links": [], "evidence_gaps": [],
                                                               "recommendations": [], "network_dna": {},
                                                               "entity_priorities": []})
            from types import SimpleNamespace
            report = SimpleNamespace(id="R-CASE-1", report_type="investigation_summary",
                                     title="Integrity Report", sections=[], generated_at="2026-09-18T00:00:00Z")
            await svc.register_report(case_id=case_id, report=report, actor_id=1)
            events = await svc.get_events(case_id)
            kinds = {e["event_type"] for e in events}
            assert {"ANALYST_DECISION", "INTELLIGENCE_SNAPSHOT", "REPORT_GENERATED"} <= kinds

    async def test_case_isolation(self, integrity_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                        filename="fir.txt", evidence_hash="A" * 64,
                                        content_hash="H1", actor_id=None)
            other = await svc.register_evidence(case_id=99999, source_id="SRC-OTHER", source_type="CDR",
                                                filename="x.csv", evidence_hash="B" * 64,
                                                content_hash="H2", actor_id=None)
            events = await svc.get_events(case_id)
            assert all(e["case_id"] == str(case_id) for e in events)
            assert not any(e["entity_id"] == "SRC-OTHER" for e in events)
            assert other["case_id"] == "99999"

    async def test_outbox_failure_marks_failed_and_continues(self, integrity_ctx, monkeypatch):
        from app.blockchain.adapters.local import LocalLedgerStore
        from app.blockchain.service import BlockchainIntegrityService
        S = integrity_ctx["S"]
        case_id = integrity_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)

            async def _boom(*args, **kwargs):
                raise RuntimeError("ledger down")

            monkeypatch.setattr(LocalLedgerStore, "append_block", _boom)
            registered = await svc.register_evidence(
                case_id=case_id, source_id="SRC-1", source_type="FIR", filename="fir.txt",
                evidence_hash="A" * 64, content_hash="H1", actor_id=None,
            )
            # Pipeline continues; evidence row exists with PENDING transaction.
            assert registered["source_id"] == "SRC-1"
            row = await EvidenceIntegrityRepository(session).latest_for_source(str(case_id), "SRC-1")
            assert row is not None
            status = await svc.pending_count(case_id)
            assert status >= 1
            summary = await svc.case_summary(case_id)
            assert summary["chain_status"] in ("VALID", "UNAVAILABLE")


from app.repositories.integrity_repository import EvidenceIntegrityRepository  # noqa: E402

# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_ctx(db_client: TestClient):
    resp = db_client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    assert resp.status_code == 200
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    case = db_client.post("/api/v1/cases", json={"title": "Integrity API Case", "priority": "HIGH"}, headers=auth)
    assert case.status_code == 201
    return {"auth": auth, "client": db_client, "cn": case.json()["case_number"]}


class TestIntegrityAPI:
    def _upload(self, ctx, content: bytes, filename: str = "cdr.csv") -> str:
        up = ctx["client"].post(
            f"/api/v1/cases/{ctx['cn']}/sources/upload",
            headers=ctx["auth"],
            files={"file": (filename, content, "text/csv")},
            data={"source_type": "CDR"},
        )
        assert up.status_code == 201, up.text
        body = up.json()
        assert body["evidence_hash"], "upload must expose the evidence hash"
        return body["source_id"]

    def test_integrity_endpoints_require_auth(self, api_ctx):
        r = api_ctx["client"].get(f"/api/v1/integrity/{api_ctx['cn']}")
        assert r.status_code == 401

    def test_upload_creates_integrity_chain_and_verifies(self, api_ctx):
        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["cn"]
        self._upload(api_ctx, b"caller,receiver\nN-1,N-2\n")

        summary = client.get(f"/api/v1/integrity/{cn}", headers=auth)
        assert summary.status_code == 200
        body = summary.json()
        assert body["chain_status"] in ("VALID", "UNAVAILABLE")
        assert body["blocks"] >= 1
        assert body["events"] >= 1
        assert body["evidence_registered"] >= 1

        events = client.get(f"/api/v1/integrity/{cn}/events", headers=auth)
        assert events.status_code == 200
        kinds = {e["event_type"] for e in events.json()["events"]}
        assert "EVIDENCE_REGISTERED" in kinds

        verified = client.post(f"/api/v1/integrity/{cn}/verify", headers=auth)
        assert verified.status_code == 200
        check = verified.json()
        assert check["evidence_checked"] >= 1
        assert check["evidence_verified"] >= 1
        assert check["chain_valid"] is True

    def test_evidence_status_endpoint_contract(self, api_ctx):
        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["cn"]
        source_id = self._upload(api_ctx, b"caller,receiver\nN-1,N-2\n")
        ev = client.get(f"/api/v1/integrity/{cn}/evidence/{source_id}", headers=auth)
        assert ev.status_code == 200
        assert ev.json()["status"] in ("VERIFIED", "MISMATCH", "UNAVAILABLE", "PENDING")
        hist = client.get(f"/api/v1/integrity/{cn}/evidence/{source_id}/history", headers=auth)
        assert hist.status_code == 200
        assert hist.json()["versions"]

    def test_case_isolation_via_api(self, api_ctx, db_client: TestClient):
        auth = api_ctx["auth"]
        case_b = db_client.post("/api/v1/cases", json={"title": "Other", "priority": "LOW"}, headers=auth)
        cn_b = case_b.json()["case_number"]

        upload_a = db_client.post(
            f"/api/v1/cases/{api_ctx['cn']}/sources/upload",
            headers=auth, files={"file": ("a.csv", b"caller,receiver\nN-1,N-2\n", "text/csv")},
            data={"source_type": "CDR"},
        )
        assert upload_a.status_code == 201
        upload_b = db_client.post(
            f"/api/v1/cases/{cn_b}/sources/upload",
            headers=auth, files={"file": ("b.csv", b"caller,receiver\nP-9,P-8\n", "text/csv")},
            data={"source_type": "CDR"},
        )
        assert upload_b.status_code == 201

        events_a = db_client.get(f"/api/v1/integrity/{api_ctx['cn']}/events", headers=auth).json()["events"]
        events_b = db_client.get(f"/api/v1/integrity/{cn_b}/events", headers=auth).json()["events"]
        tx_a = {e["transaction_id"] for e in events_a}
        tx_b = {e["transaction_id"] for e in events_b}
        assert tx_a.isdisjoint(tx_b)
        # Case B's ledger must not reference Case A's source identifiers.
        ids_b = {e.get("entity_id") for e in events_b}
        assert "A" not in ids_b
        assert "B" in ids_b

    def test_decision_and_intelligence_and_report_integrity_api(self, api_ctx):
        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["cn"]
        # Intelligence snapshot registered on first build.
        intel = client.get(f"/api/v1/cases/{cn}/intelligence", headers=auth)
        assert intel.status_code == 200
        intel_verify = client.post(f"/api/v1/integrity/{cn}/verify/intelligence", headers=auth)
        assert intel_verify.status_code == 200
        assert intel_verify.json()["status"] in ("VERIFIED", "UNAVAILABLE")

        # Analyst decision.
        dec = client.post(f"/api/v1/cases/{cn}/potential-links/decision",
                          json={"source": "P-1002", "target": "P-1003", "decision": "DEFER"}, headers=auth)
        assert dec.status_code == 200

        # Report.
        rep = client.post("/api/v1/reports/generate",
                          json={"report_type": "network_analysis", "case_number": cn},
                          headers=auth)
        assert rep.status_code == 201
        rep_verify = client.post(f"/api/v1/integrity/{cn}/verify/report/{rep.json()['id']}", headers=auth)
        assert rep_verify.status_code == 200
        assert rep_verify.json()["status"] in ("VERIFIED", "UNAVAILABLE")

        kinds = {e["event_type"] for e in client.get(f"/api/v1/integrity/{cn}/events", headers=auth).json()["events"]}
        assert "ANALYST_DECISION" in kinds
        assert "INTELLIGENCE_SNAPSHOT" in kinds
        assert "REPORT_GENERATED" in kinds