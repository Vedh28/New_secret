"""Real file parsing, header schema detection and data-quality metrics.

Parses uploaded source files (CSV / JSON / TXT, XLSX when openpyxl is
available) into canonical records consumable by the ingestion pipeline, and
computes honest quality stats (total / valid / invalid / duplicates / missing /
score). Unsupported formats return an explicit error instead of pretending.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

# Hard ceiling on records parsed per file (prototype guard).
MAX_RECORDS = 200_000

# Canonical field -> candidate header names (normalized: lower, no space/-/_).
_SCHEMAS: dict[str, dict[str, tuple[str, ...]]] = {
    "CDR": {
        "caller_phone": ("caller", "callerphone", "callernumber", "source", "aparty", "from"),
        "receiver_phone": ("receiver", "receiverphone", "receivernumber", "destination", "bparty", "to"),
        "timestamp": ("timestamp", "time", "datetime", "datetimecalltime", "calltime"),
        "duration": ("duration", "dursec", "callduration", "durationsec"),
    },
    "TRANSACTION": {
        "sender": ("sender", "fromaccount", "debitaccount", "sourceaccount", "from"),
        "receiver": ("receiver", "toaccount", "creditaccount", "destinationaccount", "to"),
        "amount": ("amount", "value", "amt", "transactionamount"),
        "timestamp": ("timestamp", "time", "datetime", "txntime", "transactiontime"),
    },
    "VEHICLE": {
        "vehicle": ("vehicleid", "vehicleno", "regno", "registration", "registrationno", "numberplate"),
        "owner": ("owner", "ownername", "registeredowner"),
        "timestamp": ("timestamp", "time", "datetime"),
    },
    "LOCATION": {
        "location": ("location", "area", "place", "locus", "site"),
        "entity": ("entity", "person", "phone", "entityid"),
        "latitude": ("lat", "latitude"),
        "longitude": ("lon", "lng", "longitude"),
        "timestamp": ("timestamp", "time", "datetime"),
    },
}

# Canonical fields a record must carry to count as valid.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "CDR": ("caller_phone", "receiver_phone"),
    "TRANSACTION": ("sender", "receiver", "amount"),
    "VEHICLE": ("vehicle",),
    "LOCATION": ("location",),
}


@dataclass
class ParsedFile:
    """Result of parsing one uploaded file."""

    format: str
    records: list[dict] = field(default_factory=list)      # {id, source_type, timestamp, text, fields}
    raw_text: str = ""
    error: str | None = None
    quality: dict = field(default_factory=dict)


def _normalize_header(h: str) -> str:
    return re.sub(r"[\s\-_\.]", "", h).lower()


def _canonical_schema(source_type: str, headers: list[str]) -> dict[str, str]:
    """Map raw header names to canonical field names for a source type."""
    lookup = {
        _normalize_header(alias): canonical
        for canonical, aliases in _SCHEMAS.get(source_type, {}).items()
        for alias in aliases
    }
    mapped: dict[str, str] = {}
    for header in headers:
        canonical = lookup.get(_normalize_header(header))
        if canonical is not None:
            mapped.setdefault(canonical, header)  # first match wins
    return mapped


def _canonicalize(row: dict, header_map: dict[str, str], source_type: str) -> dict[str, Any]:
    """Keep only recognized columns, renamed to canonical keys."""
    canonical: dict[str, Any] = {}
    for canonical_key, raw_header in header_map.items():
        value = row.get(raw_header)
        if value is None:
            value = row.get(canonical_key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            canonical[canonical_key] = text
    return canonical


def _row_key(source_type: str, fields: dict[str, Any]) -> str:
    fingerprint = f"{source_type}|" + "|".join(
        sorted(f"{k}={v}" for k, v in fields.items())
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _quality_stats(source_type: str, canonical_rows: list[dict[str, Any]]) -> dict:
    required = _REQUIRED.get(source_type, ())
    total = len(canonical_rows)
    valid, invalid, duplicates = 0, 0, 0
    invalid_samples: list[dict] = []
    seen: set[str] = set()

    for row in canonical_rows:
        missing = [f for f in required if not row.get(f)]
        if missing:
            invalid += 1
            if len(invalid_samples) < 10:
                invalid_samples.append({"row_id": row.get("_row_id"), "missing": missing})
            continue
        key = _row_key(source_type, {k: v for k, v in row.items() if not k.startswith("_")})
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        valid += 1

    score = round(valid * 100 / total) if total else 0
    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "duplicates": duplicates,
        "missing_required": sum(r["row_id"] is not None for r in invalid_samples),
        "quality_score": score,
        "invalid_samples": invalid_samples,
    }


def _wrap_records(source_type: str, canonical_rows: list[dict[str, Any]], raw_text: str) -> list[dict]:
    records: list[dict] = []
    for idx, row in enumerate(canonical_rows, start=1):
        fields = {k: v for k, v in row.items() if not k.startswith("_")}
        records.append(
            {
                "id": str(row.get("_row_id", idx)),
                "source_type": source_type,
                "timestamp": fields.get("timestamp", ""),
                "text": "",
                "fields": fields,
            }
        )
    return records


def _parse_csv(filename: str, content: bytes, source_type: str) -> ParsedFile:
    decoded = _decode(content)
    sample = decoded[:4096]
    dialect = None
    if sample.strip():
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            if not dialect.delimiter:
                dialect = None
        except csv.Error:
            dialect = None
    reader = csv.reader(io.StringIO(decoded), dialect or csv.excel)
    rows = list(reader)
    if not rows:
        return ParsedFile(format="CSV", error="Empty file")
    if len(rows) > MAX_RECORDS + 1:
        return ParsedFile(format="CSV", error=f"Too many rows ({len(rows)})")

    headers = [h.strip() for h in rows[0]]
    header_map = _canonical_schema(source_type, headers)
    if not header_map:
        # No recognized headers -> treat as plain text.
        return ParsedFile(format="TEXT", raw_text=decoded,
                          error=None, quality={"total": 1, "valid": 1, "invalid": 0,
                                               "duplicates": 0, "quality_score": 100})
    if _normalize_header(headers[0]) in {"", "_"}:
        return ParsedFile(format="TEXT", raw_text=decoded, error=None,
                          quality={"total": 0, "valid": 0, "invalid": 0, "duplicates": 0,
                                   "quality_score": 0})

    malformed = 0
    canonical_rows: list[dict[str, Any]] = []
    for idx, line in enumerate(rows[1:], start=2):
        if not line or all(not (c or "").strip() for c in line):
            continue
        if len(line) != len(headers):
            malformed += 1
            continue
        row = dict(zip(headers, line))
        fields = _canonicalize(row, header_map, source_type)
        if fields:
            fields["_row_id"] = idx
            canonical_rows.append(fields)

    records = _wrap_records(source_type, canonical_rows, decoded)
    quality = _quality_stats(source_type, canonical_rows)
    quality["malformed"] = malformed
    return ParsedFile(format="CSV", records=records, raw_text=decoded, quality=quality)


def _parse_json(content: bytes, source_type: str) -> ParsedFile:
    decoded = _decode(content)
    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        return ParsedFile(format="JSON", error=f"Invalid JSON: {exc}")
    if isinstance(data, dict):
        nested = data.get("records") or data.get("rows")
        if nested is None:
            text = data.get("text") or data.get("body")
            if isinstance(text, str) and text.strip():
                record = {
                    "id": "1",
                    "source_type": source_type,
                    "timestamp": str(data.get("timestamp", "")),
                    "text": text.strip(),
                    "fields": {k: v for k, v in data.items() if k not in ("id", "timestamp", "text", "body")},
                }
                return ParsedFile(
                    format="JSON",
                    records=[record],
                    raw_text=text.strip(),
                    quality={"total": 1, "valid": 1, "invalid": 0, "duplicates": 0, "quality_score": 100},
                )
            nested = [data]
        if not isinstance(nested, list):
            return ParsedFile(format="JSON", error="'records' key must be a list")
        data = nested
    if not isinstance(data, list):
        return ParsedFile(format="JSON", error="Top-level value must be an object or array")

    headers = _canonical_schema(source_type, [k for k in data[0].keys()]) if data else {}
    canonical_rows: list[dict[str, Any]] = []
    malformed = 0
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            malformed += 1
            continue
        fields = _canonicalize(item, headers, source_type) if headers else {k: v for k, v in item.items()}
        if fields:
            fields["_row_id"] = idx
            canonical_rows.append(fields)

    records = _wrap_records(source_type, canonical_rows, "")
    quality = _quality_stats(source_type, canonical_rows)
    quality["malformed"] = malformed
    return ParsedFile(format="JSON", records=records, raw_text="", quality=quality)


def _parse_xlsx(filename: str, content: bytes, source_type: str) -> ParsedFile:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - environment dependent
        return ParsedFile(format="XLSX", error="XLSX support requires openpyxl (pip install openpyxl)")
    sheet = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True).active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return ParsedFile(format="XLSX", error="Empty spreadsheet")
    headers = [str(h) if h is not None else "" for h in rows[0]]
    header_map = _canonical_schema(source_type, headers)
    canonical_rows: list[dict[str, Any]] = []
    malformed = 0
    for idx, line in enumerate(rows[1:], start=2):
        if line is None or all(v in (None, "") for v in line):
            continue
        if len(line) != len(headers):
            malformed += 1
            continue
        fields = _canonicalize(dict(zip(headers, line)), header_map, source_type)
        if fields:
            fields["_row_id"] = idx
            canonical_rows.append(fields)
    records = _wrap_records(source_type, canonical_rows, "")
    quality = _quality_stats(source_type, canonical_rows)
    quality["malformed"] = malformed
    return ParsedFile(format="XLSX", records=records, quality=quality)


def _parse_text(source_type: str, content: bytes) -> ParsedFile:
    decoded = _decode(content)
    stripped = decoded.strip()
    if not stripped:
        return ParsedFile(format="TEXT", error="Empty file")
    record = {
        "id": "1",
        "source_type": source_type,
        "timestamp": "",
        "text": stripped,
        "fields": {},
    }
    quality = {"total": 1, "valid": 1, "invalid": 0, "duplicates": 0, "quality_score": 100}
    return ParsedFile(format="TEXT", records=[record], raw_text=stripped, quality=quality)


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def detect_format(filename: str, content: bytes) -> tuple[str, str | None]:
    """Return (format, error). Error set for known-but-unsupported formats."""
    name = (filename or "").lower()
    ext = os.path.splitext(name)[1]
    if ext == ".pdf":
        return "PDF", "PDF parsing requires an OCR/text extractor — ingestion not yet wired"
    if ext in {".docx", ".doc"}:
        return "DOCX", "DOCX parsing requires a document extractor — ingestion not yet wired"
    if ext == ".xlsx":
        return "XLSX", None
    if ext == ".xls":
        return "XLSX", "Legacy .xls is not supported; convert to .xlsx or CSV"
    if ext == ".csv":
        return "CSV", None
    if ext == ".tsv":
        return "CSV", None
    if ext == ".json":
        return "JSON", None
    if ext in {".txt", ".text", ".log"}:
        return "TEXT", None
    head = content[:512].strip()
    if head and head[:1] in ("{", "["):
        try:
            json.loads(content[:65536].decode("utf-8", errors="ignore"))
            return "JSON", None
        except json.JSONDecodeError:
            pass
    if ext:
        return "TEXT", None
    return "TEXT", None


def parse_source(filename: str, content: bytes, source_type: str) -> ParsedFile:
    """Detect format, parse, and return canonical records + quality stats."""
    fmt, fmt_error = detect_format(filename, content)
    if fmt_error:
        return ParsedFile(format=fmt, error=fmt_error)
    if fmt == "CSV":
        return _parse_csv(filename, content, source_type)
    if fmt == "JSON":
        return _parse_json(content, source_type)
    if fmt == "XLSX":
        return _parse_xlsx(filename, content, source_type)
    return _parse_text(source_type, content)
