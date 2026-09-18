"""P1.1: deterministic NLP-lite extraction over synthetic free text."""
from __future__ import annotations

from app.ingestion.extraction import extract_text
from app.ingestion.records import SourceRecord


def _fir(text: str) -> SourceRecord:
    return SourceRecord(record_id="1", source_type="FIR", timestamp="", text=text)


class TestTextExtraction:
    def test_extracts_phone_vehicle_org_location(self):
        rec = _fir(
            "On 2026-09-02 at 22:10, Ramesh Verma used vehicle MH-02-AB-7890. "
            "Phone 9876543210. Orion Traders. Sector 17 warehouse."
        )
        res = extract_text(rec)
        types = {e.entity_type for e in res.entities}
        assert "PHONE" in types
        assert "VEHICLE" in types
        assert "ORGANIZATION" in types
        assert "LOCATION" in types
        assert {"PERSON", "PHONE", "VEHICLE"} <= types

    def test_phone_not_duplicated_as_account(self):
        rec = _fir("Contact 9876543210 and 9812345678 were used.")
        res = extract_text(rec)
        accounts = [e for e in res.entities if e.entity_type == "ACCOUNT"]
        assert len(accounts) == 0  # phones must not be re-tagged as accounts

    def test_person_names_extracted_with_uncertain_zero(self):
        rec = _fir("Rajesh Kumar stated that Ramesh Verma and Nihal Singh were involved.")
        res = extract_text(rec)
        people = {e.name for e in res.entities if e.entity_type == "PERSON"}
        assert {"Rajesh Kumar", "Ramesh Verma", "Nihal Singh"} <= people
        assert all(e.confidence < 0.6 for e in res.entities if e.entity_type == "PERSON")

    def test_co_location_produces_hypothesis_relationships(self):
        rec = _fir("Ramesh Verma and Nihal Singh were seen together near Dock 4.")
        res = extract_text(rec)
        assert len(res.relationships) >= 1
        for rel in res.relationships:
            assert rel.confidence <= 0.4  # hypotheses only, never confirmed
            assert rel.rel_type == "ASSOCIATED_WITH"

    def test_timestamp_extracted_from_text(self):
        rec = _fir("On 2026-09-02 at 22:10, phones 9811111111 and 9822222222 were in contact.")
        res = extract_text(rec)
        assert res.relationships, "co-located phones must produce a co-location hypothesis"
        assert all(rel.timestamp.startswith("2026-09-02") for rel in res.relationships)

    def test_no_fields_falls_back_to_text(self):
        from app.ingestion.extraction import extract

        rec = _fir("Vehicle MH-01-TEST-001 seen leaving. Contact 9876501234.")
        res = extract(rec)  # extract() triggers the free-text pass when fields empty
        entity_ids = {e.entity_id for e in res.entities}
        assert any(i.startswith("VEH-") for i in entity_ids)
        assert any(i.startswith("PHONE-") for i in entity_ids)