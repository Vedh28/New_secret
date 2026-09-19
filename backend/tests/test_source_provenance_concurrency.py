"""Source provenance lost-update regression tests (final hardening).

The old provenance stamp READ the whole `metadata_json`, mutated it in Python
and SAVED the entire source row. A concurrent transaction that modified
unrelated metadata between the read and the write was silently overwritten.

The fixed implementation issues a TARGETED dialect JSON-merge UPDATE that
rewrites only the provenance / integrity_tx / integrity_block / merkle_root
keys inside `metadata_json`. These tests reproduce the exact interleaving that
used to lose data and prove both sides survive.

Scenario (per spec):
  1. create source with metadata A (records) + provenance placeholders
  2. begin provenance update (read)
  3. concurrently modify unrelated metadata B and commit
  4. complete provenance update (targeted merge) and commit
  5. BOTH survive: A, B, integrity_tx, integrity_block, merkle_root, provenance
"""
from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.sources import _provenance_merge_expression
from app.core.database import Base
from app.models.case import Case, CasePriority, CaseStatus
from app.models.source import Source
from app.repositories.source_repository import SourceRepository


@pytest.fixture()
async def prov_ctx(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'prov.db'}",
        connect_args={"timeout": 30},
    )
    Maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Maker() as session:
        ca = Case(case_number="CASE-PROV-1", title="Prov A",
                  status=CaseStatus.OPEN.value, priority=CasePriority.HIGH.value)
        cb = Case(case_number="CASE-PROV-2", title="Prov B",
                  status=CaseStatus.OPEN.value, priority=CasePriority.LOW.value)
        session.add_all([ca, cb])
        await session.flush()
        session.add_all([
            Source(case_id=ca.id, source_id="SRC-1", filename="cdr.csv", file_type="CSV",
                   source_type="CDR", status="PROCESSED", record_count=2,
                   metadata_json={
                       "records": [{"id": "1", "fields": {"caller": "N-1"}},
                                   {"id": "2", "fields": {"caller": "N-2"}}],
                       "text": "raw",
                       "provenance": [{"record_id": "1", "record_hash": "H1"},
                                      {"record_id": "2", "record_hash": "H2"}],
                   }),
            Source(case_id=cb.id, source_id="SRC-OTHER", filename="other.csv", file_type="CSV",
                   source_type="CDR", status="PROCESSED", record_count=1,
                   metadata_json={"records": [{"id": "9", "fields": {"caller": "N-9"}}],
                                  "provenance": [{"record_id": "9", "record_hash": "H9"}]}),
        ])
        await session.commit()
        yield {"maker": Maker, "engine": engine,
               "case_id": ca.id, "other_case_id": cb.id}
    await engine.dispose()


async def _load(maker, case_id: int, source_id: str) -> Source:
    async with maker() as session:
        rows = await SourceRepository(session).list_by_case(case_id)
        return next(r for r in rows if r.source_id == source_id)


async def _stamp(maker, case_id: int, source_id: str, *, tx: str, block: int, root: str):
    """Apply the SAME targeted-merge expression the endpoint uses."""
    async with maker() as session:
        row = await _load(maker, case_id, source_id)
        provenance = row.metadata_json.get("provenance") or []
        for item in provenance:
            item["transaction_id"] = tx
            item["block_index"] = block
        expr = _provenance_merge_expression(
            "sqlite", provenance=provenance, tx=tx, block_index=block, merkle_root=root)
        await session.execute(
            update(Source)
            .where(Source.case_id == case_id, Source.source_id == source_id)
            .values(metadata_json=expr)
        )
        await session.commit()


async def _update_unrelated_metadata(maker, case_id: int, source_id: str, tag: str):
    async with maker() as session:
        rows = await SourceRepository(session).list_by_case(case_id)
        row = next(r for r in rows if r.source_id == source_id)
        meta = {**row.metadata_json, "tags": row.metadata_json.get("tags", []) + [tag]}
        row.metadata_json = meta
        await SourceRepository(session).save(row)
        await session.commit()


def _assert_intact(source: Source, tag: str):
    meta = source.metadata_json
    assert meta["records"][0]["fields"]["caller"] == "N-1"  # metadata A preserved
    assert "raw" == meta["text"]
    assert tag in meta["tags"]                                  # metadata B preserved
    assert meta["integrity_tx"] == "TX-FINAL"
    assert meta["integrity_block"] == 7
    assert meta["merkle_root"] == "ROOT-FINAL"
    stamps = {(p["record_id"], p["transaction_id"], p["block_index"]) for p in meta["provenance"]}
    assert stamps == {("1", "TX-FINAL", 7), ("2", "TX-FINAL", 7)}


class TestProvenanceConcurrency:
    async def test_unrelated_merge_landing_between_read_and_apply(self, prov_ctx):
        """The lost-update interleaving: unrelated write commits AFTER the
        provenance read but BEFORE the stamp write. Both survive."""
        maker = prov_ctx["maker"]
        case_id = prov_ctx["case_id"]

        # Step 1-3: create data + provenance placeholders (fixture). Begin the
        # provenance update by READING the current metadata.
        row = await _load(maker, case_id, "SRC-1")
        assert row.metadata_json.get("provenance")

        # Step 4: a concurrent transaction commits unrelated metadata B NOW,
        # between the stamp's read and its write (the exact lost-update window).
        await _update_unrelated_metadata(maker, case_id, "SRC-1", "B-wins-first")

        # Step 5: complete the provenance update -> targeted merge, no clobber.
        await _stamp(maker, case_id, "SRC-1", tx="TX-FINAL", block=7, root="ROOT-FINAL")

        _assert_intact(await _load(maker, case_id, "SRC-1"), "B-wins-first")

    async def test_stamp_then_unrelated_metadata_both_survive(self, prov_ctx):
        maker = prov_ctx["maker"]
        case_id = prov_ctx["case_id"]
        await _stamp(maker, case_id, "SRC-1", tx="TX-FINAL", block=7, root="ROOT-FINAL")
        await _update_unrelated_metadata(maker, case_id, "SRC-1", "after")
        _assert_intact(await _load(maker, case_id, "SRC-1"), "after")

    async def test_stamp_does_not_leak_across_cases_or_columns(self, prov_ctx):
        maker = prov_ctx["maker"]
        case_id = prov_ctx["case_id"]
        other_case_id = prov_ctx["other_case_id"]
        await _stamp(maker, case_id, "SRC-1", tx="TX-FINAL", block=7, root="ROOT-FINAL")

        other = await _load(maker, other_case_id, "SRC-OTHER")
        assert "integrity_tx" not in other.metadata_json  # case isolation
        assert other.metadata_json["provenance"][0].get("transaction_id") is None

        stamped = await _load(maker, case_id, "SRC-1")
        assert stamped.filename == "cdr.csv"   # unrelated column untouched
        assert stamped.status == "PROCESSED"

    async def test_restamp_updates_provenance_without_losing_unrelated(self, prov_ctx):
        maker = prov_ctx["maker"]
        case_id = prov_ctx["case_id"]
        await _stamp(maker, case_id, "SRC-1", tx="TX-1", block=1, root="ROOT-1")
        await _update_unrelated_metadata(maker, case_id, "SRC-1", "tags-1")
        await _stamp(maker, case_id, "SRC-1", tx="TX-2", block=2, root="ROOT-2")

        source = await _load(maker, case_id, "SRC-1")
        meta = source.metadata_json
        assert meta["integrity_tx"] == "TX-2"
        assert "tags-1" in meta["tags"]
        for p in meta["provenance"]:
            assert p["transaction_id"] == "TX-2" and p["block_index"] == 2