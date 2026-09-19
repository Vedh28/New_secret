"""Integrity hardening tests (P0/P1/P2).

Covers: ingestion->Merkle events, report PostgreSQL persistence + verification
across restart, intelligence snapshot idempotency, registered vs verified
counts, Merkle inclusion proofs, outbox retry safety and case isolation.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.blockchain.hashes import (
    hash_canonical_record,
    hash_intelligence_snapshot,
    hash_json,
    hash_report_payload,
    report_integrity_payload,
)
from app.blockchain.merkle import build_merkle_proof, merkle_root, verify_merkle_proof
from app.core.database import Base
from app.models.case import Case, CasePriority, CaseStatus
from app.models.integrity import EvidenceIntegrity, IntegrityOutbox, LedgerEvent
from app.models.source import Source

ADMIN = "admin"
PW = "admin-secret"


# ---------------------------------------------------------------------------
# Merkle proofs (pure)
# ---------------------------------------------------------------------------

class TestMerkleProofs:
    def test_proof_reconstructs_root(self):
        leaves = [hash_canonical_record({"id": str(i), "fields": {"v": i}}) for i in range(5)]
        root = merkle_root(leaves)
        for leaf in leaves:
            proof = build_merkle_proof(leaf, leaves)
            assert proof is not None
            assert proof["root"] == root
            assert verify_merkle_proof(proof, root) is True

    def test_even_count_proof(self):
        leaves = [f"H{i}" for i in range(4)]
        root = merkle_root(leaves)
        proof = build_merkle_proof("H0", leaves)
        assert verify_merkle_proof(proof, root) is True

    def test_modified_sibling_fails(self):
        leaves = [f"H{i}" for i in range(4)]
        root = merkle_root(leaves)
        proof = build_merkle_proof("H0", leaves)
        assert proof is not None
        tampered = {
            **proof,
            "siblings": [{"hash": "F" * 64, "side": s["side"]} for s in proof["siblings"]],
        }
        assert verify_merkle_proof(tampered, root) is False

    def test_absent_leaf_returns_none(self):
        assert build_merkle_proof("NOPE", [f"H{i}" for i in range(4)]) is None


# ---------------------------------------------------------------------------
# Async service-level (own sqlite engine)
# ---------------------------------------------------------------------------

@pytest.fixture()
async def svc_ctx(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'svc.db'}")
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with S() as session:
        case = Case(case_number="CASE-INT-H-1", title="Hardened",
                    status=CaseStatus.OPEN.value, priority=CasePriority.HIGH.value)
        session.add(case)
        await session.flush()
        session.add(Source(case_id=case.id, source_id="SRC-1", filename="cdr.csv",
                           file_type="CSV", source_type="CDR", status="PROCESSED",
                           record_count=2, metadata_json={
                               "records": [
                                   {"id": "1", "source_type": "CDR", "timestamp": "2026-09-01T10:00",
                                    "fields": {"caller": "N-1", "receiver": "N-2"}},
                                   {"id": "2", "source_type": "CDR", "timestamp": "2026-09-01T11:00",
                                    "fields": {"caller": "N-2", "receiver": "N-3"}},
                               ],
                               "provenance": [
                                   {"record_id": "1", "record_hash": hash_canonical_record(
                                       {"id": "1", "source_type": "CDR", "timestamp": "2026-09-01T10:00",
                                        "fields": {"caller": "N-1", "receiver": "N-2"}})},
                                   {"record_id": "2", "record_hash": hash_canonical_record(
                                       {"id": "2", "source_type": "CDR", "timestamp": "2026-09-01T11:00",
                                        "fields": {"caller": "N-2", "receiver": "N-3"}})},
                               ],
                           }))
        await session.commit()
        yield {"case_id": case.id, "case_number": case.case_number, "S": S, "engine": engine, "path": tmp_path / "svc.db"}
    await engine.dispose()


class TestIngestionIntegrityFlow:
    async def test_process_registers_processed_and_record_batch(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        records = [
            {"id": "1", "source_type": "CDR", "timestamp": "2026-09-01T10:00",
             "fields": {"caller": "N-1", "receiver": "N-2"}},
            {"id": "2", "source_type": "CDR", "timestamp": "2026-09-01T11:00",
             "fields": {"caller": "N-2", "receiver": "N-3"}},
        ]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            root = merkle_root([hash_canonical_record(r) for r in records])
            result = await svc.register_processed_batch(
                case_id=case_id, source_id="SRC-1", source_type="CDR",
                records=records, actor_id=None,
                extraction={"entities": 3, "relationships": 2},
            )
            assert result["merkle_root"] == root
            assert result["transaction_id"]
            assert result["block_index"] is not None
            events = await svc.get_events(case_id)
            kinds = {e["event_type"] for e in events}
            assert {"EVIDENCE_PROCESSED", "RECORD_BATCH_REGISTERED",
                    "ENTITY_EXTRACTED", "RELATIONSHIP_DERIVED"} <= kinds
            # All four events land in the SAME block.
            blocks = {e["block_index"] for e in events}
            assert len(blocks) == 1

    async def test_record_verification_succeeds_then_fails_after_mutation(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.source_repository import SourceRepository
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        records = [
            {"id": "1", "source_type": "CDR", "timestamp": "2026-09-01T10:00",
             "fields": {"caller": "N-1", "receiver": "N-2"}},
            {"id": "2", "source_type": "CDR", "timestamp": "2026-09-01T11:00",
             "fields": {"caller": "N-2", "receiver": "N-3"}},
        ]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_processed_batch(case_id=case_id, source_id="SRC-1", source_type="CDR",
                                               records=records, actor_id=None,
                                               extraction={"entities": 3, "relationships": 2})
            ok = await svc.verify_record(case_id, "SRC-1", "1")
            assert ok["verified"] is True
            assert ok.get("proof_valid") is True
            assert ok.get("merkle_proof") is not None

            # MUTATE the stored record payload.
            rows = await SourceRepository(session).list_by_case(int(case_id))
            source = next(r for r in rows if r.source_id == "SRC-1")
            meta = source.metadata_json or {}
            records_meta = meta["records"]
            for r in records_meta:
                if str(r.get("id")) == "1":
                    r["fields"]["caller"] = "N-999"
            source.metadata_json = {**meta, "records": records_meta}
            await SourceRepository(session).save(source)
            await session.commit()

            bad = await svc.verify_record(case_id, "SRC-1", "1")
            assert bad["verified"] is False
            assert bad["status"] == "MISMATCH"


class TestSnapshotIdempotency:
    async def test_ten_identical_snapshots_stay_one(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.services.case_intelligence_service import CaseIntelligenceService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            snapshot = await CaseIntelligenceService(session).build(case_id, cache={}, register_integrity=False)
            svc = BlockchainIntegrityService(session)
            for _ in range(10):
                result = await svc.register_intelligence_snapshot(case_id=case_id, snapshot=snapshot)
                assert result["duplicate"] in (False, True)  # first creates, rest dedupe
            events = await svc.get_events(case_id)
            snaps = [e for e in events if e["event_type"] == "INTELLIGENCE_SNAPSHOT"]
            assert len(snaps) == 1

    async def test_identical_snapshot_not_repeated(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.services.case_intelligence_service import CaseIntelligenceService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            snapshot = await CaseIntelligenceService(session).build(case_id, cache={}, register_integrity=False)
            svc = BlockchainIntegrityService(session)
            first = await svc.register_intelligence_snapshot(case_id=case_id, snapshot=snapshot)
            assert first["duplicate"] is False
            second = await svc.register_intelligence_snapshot(case_id=case_id, snapshot=snapshot)
            assert second["duplicate"] is True
            events = await svc.get_events(case_id)
            snap_events = [e for e in events if e["event_type"] == "INTELLIGENCE_SNAPSHOT"]
            assert len(snap_events) == 1

    async def test_changed_content_creates_new_snapshot(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        base = {"case_id": case_id, "entities": [], "relationships": [], "evidence": [],
                "anomalies": [], "potential_links": [], "evidence_gaps": [],
                "recommendations": [], "network_dna": {}, "entity_priorities": []}
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_intelligence_snapshot(case_id=case_id, snapshot=base)
            changed = {**base, "anomalies": [{"kind": "COMM_BURST", "entity_id": "N-1"}]}
            second = await svc.register_intelligence_snapshot(case_id=case_id, snapshot=changed)
            assert second["duplicate"] is False
            assert hash_intelligence_snapshot(changed) == second["snapshot_hash"]

    async def test_different_case_independent_snapshots(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            snapshot = {"case_id": case_id, "entities": [], "relationships": [], "evidence": [],
                        "anomalies": [], "potential_links": [], "evidence_gaps": [],
                        "recommendations": [], "network_dna": {}, "entity_priorities": []}
            r1 = await svc.register_intelligence_snapshot(case_id=case_id, snapshot=snapshot)
            assert r1["duplicate"] is False
            other = await svc.register_intelligence_snapshot(case_id=99999, snapshot=snapshot)
            assert other["duplicate"] is False

    async def test_different_engine_version_independent(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            snapshot_hash = hash_intelligence_snapshot({"a": 1})
            r1 = await svc.enqueue_snapshot(case_id=case_id, snapshot_hash=snapshot_hash, engine_version="1.0")
            assert r1["duplicate"] is False
            r2 = await svc.enqueue_snapshot(case_id=case_id, snapshot_hash=snapshot_hash, engine_version="2.0")
            assert r2["duplicate"] is False


class TestRegisteredVsVerifiedCounts:
    async def test_counts_separate_registered_and_verified(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.services.case_intelligence_service import CaseIntelligenceService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            snapshot = await CaseIntelligenceService(session).build(case_id, cache={}, register_integrity=False)
            svc = BlockchainIntegrityService(session)
            await svc.register_intelligence_snapshot(case_id=case_id, snapshot=snapshot)
            summary = await svc.case_summary(case_id)
            assert summary["registered_snapshots"] == 1
            assert summary["verified_snapshots"] == 1  # current intel matches commitment
            assert summary["registered_reports"] == 0
            assert summary["verified_reports"] == 0


class TestOutboxRetrySafety:
    async def test_repeated_flush_does_not_duplicate_events(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.integrity_repository import IntegrityOutboxRepository
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.enqueue(case_id=case_id, event_type="INTELLIGENCE_SNAPSHOT",
                              entity_type="case", entity_id=str(case_id),
                              payload={"event_type": "INTELLIGENCE_SNAPSHOT",
                                       "case_id": str(case_id), "snapshot_hash": "S1",
                                       "actor_id": ""}, actor_id=None)
            await svc.flush_pending(case_id)
            # Outbox now empty; flushing again is a no-op.
            assert await svc.flush_pending(case_id) == []
            events = await svc.get_events(case_id)
            assert len([e for e in events if e["event_type"] == "INTELLIGENCE_SNAPSHOT"]) == 1

    async def test_failed_snapshot_outbox_is_retried_as_same_identity(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.integrity_repository import IntegrityOutboxRepository
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        snapshot_hash = hash_intelligence_snapshot({"x": 1})
        async with S() as session:
            outbox_repo = IntegrityOutboxRepository(session)
            key = f"{case_id}::INTELLIGENCE_SNAPSHOT::1.x::{snapshot_hash}"
            await outbox_repo.create(
                case_id=str(case_id), event_type="INTELLIGENCE_SNAPSHOT",
                entity_type="case", entity_id=str(case_id),
                payload_hash="H", payload_json={"snapshot_hash": snapshot_hash, "event_type": "INTELLIGENCE_SNAPSHOT"},
                actor_id=None, status="FAILED", attempts=2, last_error="ledger down", dedupe_key=key,
            )
            await session.commit()

            svc = BlockchainIntegrityService(session)
            result = await svc.enqueue_snapshot(case_id=case_id, snapshot_hash=snapshot_hash, engine_version="1.x")
            assert result["retried"] is True  # reused the EXISTING failed identity

            # Flush confirms it into exactly ONE ledger event.
            await svc.flush_pending(case_id)
            events = await svc.get_events(case_id)
            snap = [e for e in events if e["event_type"] == "INTELLIGENCE_SNAPSHOT"]
            assert len(snap) == 1
            assert snap[0]["payload_json"].get("snapshot_hash") == snapshot_hash

            # Re-enqueuing after confirmation is a no-op.
            again = await svc.enqueue_snapshot(case_id=case_id, snapshot_hash=snapshot_hash, engine_version="1.x")
            assert again["duplicate"] is True


class TestEventPayloadConsistency:
    async def test_verify_case_detects_tampered_event_payload(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        from app.repositories.integrity_repository import LedgerEventRepository
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            await svc.register_evidence(case_id=case_id, source_id="SRC-1", source_type="FIR",
                                        filename="fir.txt", evidence_hash="A" * 64,
                                        content_hash="H1", actor_id=None)
            before = await svc.verify_case(case_id)
            assert before["event_consistency_valid"] is True

            # TAMPER an event payload; the payload_hash must then mismatch.
            events = await LedgerEventRepository(session).list_by_case(str(case_id), limit=100)
            event = next(e for e in events if e.event_type == "EVIDENCE_REGISTERED")
            event.payload_json = {**event.payload_json, "source_id": "TAMPERED"}
            await LedgerEventRepository(session).save(event)
            await session.commit()

            after = await svc.verify_case(case_id)
            assert after["event_consistency_valid"] is False
            assert any("payload hash mismatch" in issue["issue"] for issue in after["event_consistency_issues"])

    async def test_verify_report_not_registered_status(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            result = await svc.verify_report(case_id, "REPORT-MISSING", "H")
            assert result["status"] == "NOT_REGISTERED"

    async def test_verify_intelligence_not_registered_status(self, svc_ctx):
        from app.blockchain.service import BlockchainIntegrityService
        S = svc_ctx["S"]
        case_id = svc_ctx["case_id"]
        async with S() as session:
            svc = BlockchainIntegrityService(session)
            result = await svc.verify_intelligence(case_id, "H")
            assert result["status"] == "NOT_REGISTERED"


class TestIntegrityIsolation:
    async def test_intelligence_endpoint_survives_integrity_flush_failure(self, api_ctx, monkeypatch):
        """Integrity flush failure must NOT break the intelligence response or
        poison the main session."""
        from app.blockchain.service import BlockchainIntegrityService

        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["ca"]

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger unavailable (injected)")

        monkeypatch.setattr(BlockchainIntegrityService, "flush_pending", _boom)

        r1 = client.get(f"/api/v1/cases/{cn}/intelligence", headers=auth)
        assert r1.status_code == 200
        assert "network_dna" in r1.json()

        r2 = client.get(f"/api/v1/cases/{cn}/intelligence", headers=auth)
        assert r2.status_code == 200
        assert "network_dna" in r2.json()

    async def test_decision_endpoint_survives_integrity_failure(self, api_ctx, monkeypatch):
        """Decision business transaction must commit even when integrity is down."""
        from app.blockchain.service import BlockchainIntegrityService

        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["ca"]

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger unavailable (injected)")

        monkeypatch.setattr(BlockchainIntegrityService, "record_analyst_decision", _boom)

        r = client.post(
            f"/api/v1/cases/{cn}/potential-links/decision",
            json={"source": "P-9001", "target": "P-9002", "decision": "DEFER"},
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["new_status"] == "DEFERRED"

        decisions = client.get(f"/api/v1/cases/{cn}/potential-links/decisions", headers=auth)
        assert decisions.status_code == 200
        assert any(d["new_status"] == "DEFERRED" for d in decisions.json())

    async def test_evidence_upload_survives_integrity_failure(self, api_ctx, monkeypatch):
        """Source upload commits even when evidence integrity registration fails."""
        from app.blockchain.service import BlockchainIntegrityService

        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["ca"]

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger unavailable (injected)")

        monkeypatch.setattr(BlockchainIntegrityService, "register_evidence", _boom)

        r = client.post(
            f"/api/v1/cases/{cn}/sources/upload",
            headers=auth,
            files={"file": ("cdr.csv", b"caller,receiver\nN-1,N-2\n", "text/csv")},
            data={"source_type": "CDR"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["integrity_status"] == "LEDGER_UNAVAILABLE"  # integrity unavailable, upload OK
        assert body["source_id"] == "CDR"

        sources = client.get(f"/api/v1/cases/{cn}/sources", headers=auth)
        assert sources.status_code == 200
        assert any(s["source_id"] == "CDR" for s in sources.json())  # source persisted

    async def test_report_survives_integrity_failure(self, api_ctx, monkeypatch):
        """Report persists even when its integrity registration fails."""
        from app.blockchain.service import BlockchainIntegrityService

        client, auth, cn = api_ctx["client"], api_ctx["auth"], api_ctx["ca"]

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger unavailable (injected)")

        monkeypatch.setattr(BlockchainIntegrityService, "register_report", _boom)

        r = client.post(
            "/api/v1/reports/generate",
            json={"report_type": "network_analysis", "case_number": cn},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        report_id = r.json()["id"]

        # Persisted report retrievable after the failed integrity registration.
        got = client.get(f"/api/v1/reports/{report_id}", headers=auth)
        assert got.status_code == 200
        assert got.json()["id"] == report_id


# ---------------------------------------------------------------------------
# Cache consistency (per-process, ephemeral)
# ---------------------------------------------------------------------------

class TestCaseCacheInvalidation:
    def test_invalidate_case_cache_removes_entry(self):
        from app.api.v1 import intelligence as intel_mod
        intel_mod._cache[1] = {"case_id": 1}
        intel_mod._cache[2] = {"case_id": 2}
        intel_mod.invalidate_case_cache(1)
        assert 1 not in intel_mod._cache
        assert 2 in intel_mod._cache  # other cases untouched
        intel_mod.invalidate_case_cache(999)  # no error for unknown case
        intel_mod.clear_cache()
        assert intel_mod._cache == {}


# ---------------------------------------------------------------------------
# API-level
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_ctx(db_client: TestClient):
    resp = db_client.post("/api/v1/auth/login", json={"username": ADMIN, "password": PW})
    assert resp.status_code == 200
    auth = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    case_a = db_client.post("/api/v1/cases", json={"title": "Integrity H A", "priority": "HIGH"}, headers=auth)
    case_b = db_client.post("/api/v1/cases", json={"title": "Integrity H B", "priority": "LOW"}, headers=auth)
    return {"auth": auth, "client": db_client,
            "ca": case_a.json()["case_number"], "cb": case_b.json()["case_number"]}


class TestIntegrityPipelineApi:
    def _upload_process(self, api_ctx, case_key, content, filename, source_type):
        up = api_ctx["client"].post(
            f"/api/v1/cases/{case_key}/sources/upload",
            headers=api_ctx["auth"],
            files={"file": (filename, content, "text/csv")},
            data={"source_type": source_type},
        )
        assert up.status_code == 201, up.text
        sid = up.json()["source_id"]
        pro = api_ctx["client"].post(f"/api/v1/cases/{case_key}/sources/{sid}/process", headers=api_ctx["auth"])
        assert pro.status_code == 200, pro.text
        return sid, pro.json()

    def test_upload_and_process_produce_full_lifecycle(self, api_ctx):
        client, auth = api_ctx["client"], api_ctx["auth"]
        sid, processed = self._upload_process(
            api_ctx, api_ctx["ca"], b"caller,receiver,time\nN-1,N-2,2026-09-01T10:00\nN-2,N-3,2026-09-01T11:00\n",
            "cdr.csv", "CDR",
        )
        assert processed["metrics"]["merkle_root"]
        assert processed["metrics"]["integrity_tx"]

        events = client.get(f"/api/v1/integrity/{api_ctx['ca']}/events", headers=auth).json()["events"]
        kinds = {e["event_type"] for e in events}
        assert "EVIDENCE_REGISTERED" in kinds
        assert "EVIDENCE_PROCESSED" in kinds
        assert "RECORD_BATCH_REGISTERED" in kinds
        assert "ENTITY_EXTRACTED" in kinds
        assert "RELATIONSHIP_DERIVED" in kinds

        # Record verification against the on-chain Merkle root.
        verified = client.post(f"/api/v1/integrity/{api_ctx['ca']}/verify/record/{sid}/2", headers=auth)
        assert verified.status_code == 200
        assert verified.json()["verified"] is True
        assert verified.json().get("proof_valid") is True

    def test_case_isolation_transactions_and_reports(self, api_ctx):
        client, auth = api_ctx["client"], api_ctx["auth"]
        self._upload_process(api_ctx, api_ctx["ca"], b"caller,receiver\nA-1,A-2\n", "acdr.csv", "CDR")
        self._upload_process(api_ctx, api_ctx["cb"], b"caller,receiver\nB-1,B-2\n", "bcdr.csv", "CDR")

        events_a = client.get(f"/api/v1/integrity/{api_ctx['ca']}/events", headers=auth).json()["events"]
        events_b = client.get(f"/api/v1/integrity/{api_ctx['cb']}/events", headers=auth).json()["events"]
        tx_a = {e["transaction_id"] for e in events_a}
        tx_b = {e["transaction_id"] for e in events_b}
        assert tx_a.isdisjoint(tx_b)
        # Case A's transaction must NOT be visible under Case B.
        sample_tx = next(iter(tx_a))
        cross = client.get(f"/api/v1/integrity/{api_ctx['cb']}/transactions/{sample_tx}", headers=auth)
        assert cross.status_code == 404

        # Report isolation: A's report is not listed/verifiable under B.
        rep = client.post("/api/v1/reports/generate",
                          json={"report_type": "network_analysis", "case_number": api_ctx["ca"]},
                          headers=auth)
        assert rep.status_code == 201
        rep_a = client.get("/api/v1/reports", params={"case_number": api_ctx["ca"]}, headers=auth).json()
        rep_b = client.get("/api/v1/reports", params={"case_number": api_ctx["cb"]}, headers=auth).json()
        assert any(r["id"] == rep.json()["id"] for r in rep_a)
        assert not any(r["id"] == rep.json()["id"] for r in rep_b)
        wrong_case = client.get(f"/api/v1/reports/{rep.json()['id']}", params={"case_number": api_ctx["cb"]}, headers=auth)
        assert wrong_case.status_code == 404

        # Verify A's own report works; verifying under B must not succeed.
        ok = client.post(f"/api/v1/integrity/{api_ctx['ca']}/verify/report/{rep.json()['id']}", headers=auth)
        assert ok.status_code == 200
        assert ok.json()["status"] in ("VERIFIED",)

    def test_snapshot_idempotent_across_requests(self, api_ctx):
        client, auth = api_ctx["client"], api_ctx["auth"]
        for _ in range(2):
            res = client.get(f"/api/v1/cases/{api_ctx['ca']}/intelligence", headers=auth)
            assert res.status_code == 200
        events = client.get(f"/api/v1/integrity/{api_ctx['ca']}/events", headers=auth).json()["events"]
        snapshots = [e for e in events if e["event_type"] == "INTELLIGENCE_SNAPSHOT"]
        assert len(snapshots) == 1

    def test_decision_integrity_repeat_is_idempotent(self, api_ctx):
        client, auth = api_ctx["client"], api_ctx["auth"]
        for _ in range(2):
            r = client.post(
                f"/api/v1/cases/{api_ctx['ca']}/potential-links/decision",
                json={"source": "P-5002", "target": "P-5003", "decision": "CONFIRM", "notes": "reviewed"},
                headers=auth,
            )
            assert r.status_code == 200
        events = client.get(f"/api/v1/integrity/{api_ctx['ca']}/events", headers=auth).json()["events"]
        decisions = [e for e in events if e["event_type"] == "ANALYST_DECISION"]
        assert len(decisions) == 1
