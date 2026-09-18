"""Deterministic hashing utilities (integrity layer).

Cryptographic hashes are produced ONLY from canonical, stable serializations:
- JSON is canonicalized with stable key ordering + normalized primitives
- datetime/other non-primitive values fall back to ISO-ish strings
- output is uppercase-hex SHA-256

Never hash a Python object with repr(). The same input MUST always yield the
same hash so integrity verification is deterministic.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from numbers import Number
from typing import Any

HASH_ALGORITHM = "SHA-256"

# Deterministic Canonical JSON: stable key order, compact separators, no
# environment-dependent whitespace. Primitive values are emitted as-is.
_CANONICAL_JSON = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}


def _json_default(value: Any) -> Any:
    """Normalize non-primitive values without losing determinism."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def canonical_json(payload: Any) -> str:
    """Return a stable, deterministic JSON string for any JSON-able payload."""
    return json.dumps(payload, **_CANONICAL_JSON, default=_json_default)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def hash_bytes(data: bytes) -> str:
    """SHA-256 hex digest over raw bytes."""
    return _digest(data)


def hash_text(text: str) -> str:
    """SHA-256 over UTF-8 text."""
    if text is None:
        text = ""
    return _digest(str(text).encode("utf-8"))


def hash_json(payload: Any) -> str:
    """SH-256 over the canonical JSON serialization of a payload."""
    return _digest(canonical_json(payload).encode("utf-8"))


def hash_file(path: str) -> str:
    """Streaming SHA-256 over a file path (large files)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()


def short(hash_hex: str, length: int = 8) -> str:
    """Short human-friendly prefix of a full hash."""
    if not hash_hex:
        return ""
    return hash_hex[:length]


# ---------------------------------------------------------------------------
# Evidence / snapshot / report canonical payloads (non-sensitive by design)
# ---------------------------------------------------------------------------

def canonical_evidence_payload(*, case_id, source_id, source_type, filename,
                               records: list[dict] | None = None, text: str = "") -> dict:
    """Canonical, non-sensitive representation of a persisted evidence payload.

    Records are included as their canonical normalized field dicts (already
    free of raw secrets in this system) so that a tampered stored payload is
    detectable on re-hash. Keep as small as possible.
    """
    return {
        "case_id": str(case_id),
        "source_id": str(source_id),
        "source_type": str(source_type or ""),
        "filename": str(filename or ""),
        "records": records or [],
        "text": str(text or "")[:512],
    }


def hash_evidence_payload(payload: dict) -> str:
    """Hash a canonical evidence payload."""
    return hash_json(payload)


def snapshot_integrity_payload(snapshot: dict) -> dict:
    """Extract a deterministic, non-sensitive fingerprint of an intelligence
    snapshot for integrity registration.

    Includes the analytical METRICS (counts/scores/DNA/anomaly kinds) plus
    identifiers — never raw evidence text.
    """
    return {
        "case_id": snapshot.get("case_id"),
        "engine": "CaseIntelligenceService",
        "engine_version": "1.x",
        "limits": {
            "entities": len(snapshot.get("entities") or []),
            "relationships": len(snapshot.get("relationships") or []),
            "evidence": len(snapshot.get("evidence") or []),
            "anomalies": len(snapshot.get("anomalies") or []),
            "potential_links": len(snapshot.get("potential_links") or []),
            "evidence_gaps": len(snapshot.get("evidence_gaps") or []),
            "recommendations": len(snapshot.get("recommendations") or []),
        },
        "network_dna": snapshot.get("network_dna") or {},
        "anomaly_kinds": sorted({a.get("kind") for a in snapshot.get("anomalies") or []} | {""}) if snapshot.get("anomalies") else [],
        "entity_priority_summary": [
            {"subject": p.get("subject"), "priority": round(float(p.get("priority") or 0), 1)}
            for p in (snapshot.get("entity_priorities") or [])[:8]
        ],
        "recommendation_subjects": [r.get("subject") for r in (snapshot.get("recommendations") or [])[:8]],
    }


def hash_intelligence_snapshot(snapshot: dict) -> str:
    """Hash a canonical intelligence snapshot fingerprint."""
    return hash_json(snapshot_integrity_payload(snapshot))


def report_integrity_payload(report_id: str, report_type: str, title: str,
                             sections: list, generated_at: str = "") -> dict:
    """Canonical report fingerprint (report content, not raw evidence)."""
    return {
        "report_id": report_id,
        "report_type": report_type,
        "title": title,
        "sections": [{"heading": s.heading, "body": s.body} for s in sections] if sections else [],
        "generated_at": str(generated_at or ""),
    }


def hash_report_payload(payload: dict) -> str:
    return hash_json(payload)


def hash_decision_payload(*, case_id, entity_a, entity_b, decision,
                          evidence_ids_hash, notes_hash, analyst_id,
                          snapshot_hash: str = "") -> dict:
    """Non-sensitive canonical payload for an analyst decision."""
    return {
        "case_id": str(case_id),
        "entity_a": str(entity_a),
        "entity_b": str(entity_b),
        "decision": str(decision),
        "evidence_ids_hash": str(evidence_ids_hash),
        "notes_hash": str(notes_hash),
        "analyst_id": str(analyst_id or ""),
        "intelligence_snapshot_hash": str(snapshot_hash or ""),
    }


def hash_record(record: dict) -> str:
    """Hash one canonical normalized record (deterministic)."""
    return hash_json(record)