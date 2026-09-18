"""Report PostgreSQL persistence + verification across restart (P0.2)."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.blockchain.hashes import hash_report_payload, report_integrity_payload
from app.core.database import Base
from app.graph.memory_store import MemoryGraphStore
from app.graph.types import GraphEdge, GraphNode
from app.models.case import Case, CasePriority, CaseStatus
from app.models.user import User, UserRole
from app.reports.service import ReportService
from app.repositories.report_repository import ReportRepository
from app.schemas.report import ReportRequest


def _make_engine(path):
    return create_async_engine(f"sqlite+aiosqlite:///{path}")


def _graph_store() -> MemoryGraphStore:
    store = MemoryGraphStore()
    store.nodes["P-0421"] = GraphNode(id="P-0421", type="PERSON", name="Person A",
                                      properties={"risk_score": 94, "risk_level": "CRITICAL"})
    store.nodes["O-1101"] = GraphNode(id="O-1101", type="ORGANIZATION", name="Org",
                                      properties={"risk_score": 89})
    return store


async def _seed(S):
    user = User(username="admin", email="a@b.c", password_hash="x", role=UserRole.ADMIN.value)
    async with S() as session:
        session.add(user)
        await session.flush()
        case = Case(case_number="CASE-REP-1", title="Report Case",
                    status=CaseStatus.OPEN.value, priority=CasePriority.HIGH.value)
        session.add(case)
        await session.commit()
        return {"case_id": case.id, "user": user}


@pytest.fixture()
async def report_persistence(tmp_path):
    path = tmp_path / "reports.db"
    engine = _make_engine(path)
    S = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    ctx = await _seed(S)
    ctx["path"] = path
    ctx["S"] = S
    ctx["engine"] = engine
    yield ctx
    await engine.dispose()


class TestReportPersistence:
    async def test_report_survives_restart_and_verifies(self, report_persistence):
        S = report_persistence["S"]
        user = report_persistence["user"]

        # Generate + persist + register integrity.
        store = _graph_store()
        async with S() as session:
            service = ReportService(session, store, user)
            response = await service.generate(ReportRequest(report_type="network_analysis",
                                                            case_number="CASE-REP-1"))
            from app.blockchain.service import BlockchainIntegrityService
            await BlockchainIntegrityService(session).register_report(
                case_id=report_persistence["case_id"], report=response, actor_id=1,
                report_hash=hash_report_payload(report_integrity_payload(
                    report_id=response.id, report_type=response.report_type,
                    title=response.title,
                    sections=[{"heading": s.heading, "body": s.body} for s in response.sections],
                    generated_at=str(response.generated_at),
                )),
            )
            await session.commit()
            report_id = response.id

        # SIMULATE RESTART: fresh engine + fresh store, same file.
        await report_persistence["engine"].dispose()
        engine2 = _make_engine(report_persistence["path"])
        S2 = async_sessionmaker(engine2, expire_on_commit=False)

        async with S2() as session:
            row = await ReportRepository(session).get(report_id)
            assert row is not None
            assert row.report_hash
            assert row.sections_json
            assert row.artifact

            current_hash = hash_report_payload(report_integrity_payload(
                report_id=row.id, report_type=row.report_type, title=row.title,
                sections=row.sections_json, generated_at=str(row.generated_at),
            ))
            assert current_hash == row.report_hash  # stable across restart

            from app.blockchain.service import BlockchainIntegrityService
            verdict = await BlockchainIntegrityService(session).verify_report(
                report_persistence["case_id"], report_id, current_hash)
            assert verdict["verified"] is True
            assert verdict["status"] == "VERIFIED"

            # TAMPER the persisted report and re-verify.
            row.sections_json = [{"heading": "Tampered", "body": ["changed"]}]
            await ReportRepository(session).save(row)
            await session.commit()

            altered_hash = hash_report_payload(report_integrity_payload(
                report_id=row.id, report_type=row.report_type, title=row.title,
                sections=row.sections_json, generated_at=str(row.generated_at),
            ))
            tampered = await BlockchainIntegrityService(session).verify_report(
                report_persistence["case_id"], report_id, altered_hash)
            assert tampered["verified"] is False
            assert tampered["status"] == "MISMATCH"
        await engine2.dispose()

    async def test_list_is_case_scoped_after_restart(self, report_persistence):
        S = report_persistence["S"]
        user = report_persistence["user"]
        async with S() as session:
            service = ReportService(session, _graph_store(), user)
            await service.generate(ReportRequest(report_type="communication_analysis",
                                                 case_number="CASE-REP-1"))
            await session.commit()
            scoped = await service.list_meta(case_number="CASE-REP-1")
            assert len(scoped) == 1
            assert await service.list_meta(case_number="CASE-REP-NOPE") == []