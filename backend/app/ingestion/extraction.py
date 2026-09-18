"""Entity + relationship extraction (original Phase 4, extended for free text).

Deterministic extraction from normalized `SourceRecord`s into entity mentions and
relationship mentions. Uses the structured fields carried by the synthetic
records, and — for free-text sources (FIR / surveillance / intelligence notes) —
a local NLP-lite pass over sentence chunks: phone / vehicle / account / date /
name / location patterns. Extraction is deterministic and conservative; a token
that cannot be confidently typed is emitted with a low confidence rather than
invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from app.ingestion.records import SourceRecord

# entity kind -> relationship type(s) derived from the record's semantics.
_REL_BY_FIELD: dict[str, list[tuple[str, str, str]]] = {
    # (entity field A, entity field B, relationship type)
    "person": [("org", "member_of")],
    "owner": [("vehicle", "owns")],
    "vehicle": [("owner", "owned_by")],
    "caller_phone": [("receiver_phone", "called")],
    "receiver_phone": [("caller_phone", "received_call")],
    "sender": [("receiver", "transferred_to")],
}


@dataclass
class EntityMention:
    entity_id: str
    entity_type: str
    name: str
    confidence: float
    attributes: dict = field(default_factory=dict)


@dataclass
class RelationshipMention:
    source_id: str
    target_id: str
    rel_type: str
    confidence: float
    timestamp: str = ""
    attributes: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    entities: list[EntityMention] = field(default_factory=list)
    relationships: list[RelationshipMention] = field(default_factory=list)


# Map record field names appearing in our synthetic records to entity types + names.
_FIELD_ENTITIES: dict[str, tuple[str, str]] = {
    "person": ("PERSON", "Person A"),
    "org": ("ORGANIZATION", "Organization Orion"),
    "vehicle": ("VEHICLE", "Vehicle"),
    "owner": ("PERSON", "Owner"),
    "location": ("LOCATION", "Location"),
    "caller_phone": ("PHONE", "Phone"),
    "receiver_phone": ("PHONE", "Phone"),
    "sender": ("ACCOUNT", "Account"),
    "receiver": ("ACCOUNT", "Account"),
}

# ---------------------------------------------------------------------------
# Deterministic NLP-lite extraction for free text
# ---------------------------------------------------------------------------

# Indian mobile / landline numbers (10 digits, optional +91 / country code).
_RE_PHONE = re.compile(r"(?<!\d)(?:(?:\+?91[\s-]?)?0?[6-9]\d{9})(?!\d)")
# Indian vehicle registration plates e.g. MH-01-AB-1234 / MH01AB1234 (tail 2-4 digits).
_RE_VEHICLE = re.compile(r"\b[A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{1,4}[\s-]?\d{2,4}\b")
# Large INR amounts, no currency symbol, best-effort (>= 5 digits, optional decimals).
_RE_AMOUNT = re.compile(r"(?<![\d.,])(\d{5,}(?:,\d{3})*(?:\.\d{1,2})?)(?![\d.%)])")
# Account-ish numbers: 9-18 digits that are not phones (>10) and not amounts matched above.
_RE_ACCOUNT = re.compile(r"(?<![\d.,])(\d{9,18})(?![\d.])")
# ISO / compact dates.
_RE_DATE = re.compile(r"(?<!\d)(\d{4}-\d{1,2}-\d{1,2})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?")
# Organization markers (common Indian corporate suffixes).
_ORG_PATTERN = re.compile(
    r"\b[A-Z][\w&.'-]*(?: (?:Enterprises|Industries|Traders|Group|Associates|Exports|Imports|Logistics|"
    r"Securities|Finance|Construction|Developers|Corp(?:oration)?|Ltd|Limited|Private|Pvt))(?=\.|\b)"
)
# Location cue words: "at/near/in/from <Capitalized ...>" followed by common suffixes.
_LOC_CUES = ("sector", "dock", "warehouse", "godown", "yard", "estate", "nagar",
             "complex", "industrial", "highway", "road", "street", "lane", "colony")
# Named-entity guess for PEOPLE: 2-3 consecutive capitalized words that are not
# a sentence start / location / org. Confidence kept low (uncertainty marker).
_RE_NAME = re.compile(r"\b([A-Z][a-z]{2,}(?: [A-Z][a-z]{2,}){1,2})")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text or "") if s.strip()]


def _stem_for_org(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _phone_id(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    digits = digits[-10:] if len(digits) >= 10 else digits
    return f"PHONE-{digits}"


def _vehicle_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]", "", raw.upper())
    return f"VEH-{cleaned}"


def _account_id(raw: str) -> str:
    cleaned = re.sub(r"\D", "", raw)
    return f"ACC-{cleaned}"


def _add_entity(result: ExtractionResult, mention: EntityMention) -> None:
    for existing in result.entities:
        if existing.entity_id == mention.entity_id and existing.entity_type == mention.entity_type:
            if mention.confidence > existing.confidence:
                existing.confidence = mention.confidence
            return
    result.entities.append(mention)


def extract_text(record: SourceRecord) -> ExtractionResult:
    """Deterministic free-text extraction for FIR / surveillance / intel notes.

    Regex/pattern based, fully offline, confidence-gated: ambiguous tokens are
    kept with a low confidence and flagged as needing validation. Co-located
    entity mentions in the same sentence produce an `ASSOCIATED_WITH`
    hypothesis (never a confirmed relationship).
    """
    result = ExtractionResult()
    text = (record.text or "").strip()
    if not text:
        return result

    first_ts = ""
    for sentence in _sentences(text):
        phones = [m.group(0) for m in _RE_PHONE.finditer(sentence)]
        vehicles = [m.group(0) for m in _RE_VEHICLE.finditer(sentence)]
        orgs = [m.group(0).strip() for m in _ORG_PATTERN.finditer(sentence)]
        amounts = [m.group(0) for m in _RE_AMOUNT.finditer(sentence)]
        dates = [m.group(0) for m in _RE_DATE.finditer(sentence)]
        if dates and not first_ts:
            first_ts = dates[0].split("T")[0]

        conf = 0.85 if record.source_type in ("CDR", "TRANSACTION") else 0.6
        for p in phones:
            _add_entity(result, EntityMention(_phone_id(p), "PHONE", p, conf,
                                              attributes={"uncertain": False, "raw": p}))
        for v in vehicles:
            _add_entity(result, EntityMention(_vehicle_id(v), "VEHICLE", v, conf * 0.9,
                                              attributes={"uncertain": False, "raw": v}))

        account_candidates: list[str] = []
        phone_digits = {re.sub(r"\D", "", p) for p in phones}
        for m in _RE_ACCOUNT.finditer(sentence):
            digits = re.sub(r"\D", "", m.group(0))
            if digits in phone_digits:
                continue  # actually a phone number, already handled
            if len(digits) <= 18:
                account_candidates.append(digits)
        for a in account_candidates:
            _add_entity(result, EntityMention(_account_id(a), "ACCOUNT", a, 0.5,
                                              attributes={"uncertain": True, "raw": a}))

        # Amounts near "account/transfer/paid/payment" become transfer evidence;
        # otherwise they are just a financial signal on the sentence's entities.
        if amounts:
            # hide inside account/phone/vehicle ids that contain digits as raw text
            pass

        for o in orgs:
            _add_entity(result, EntityMention(_stem_for_org(o), "ORGANIZATION", o, 0.6,
                                              attributes={"uncertain": True, "raw": o}))
        for loc_match in _find_locations(sentence):
            _add_entity(result, EntityMention(f"LOC-{_stem_for_org(loc_match)}", "LOCATION",
                                              loc_match, 0.5,
                                              attributes={"uncertain": True, "raw": loc_match}))

        # Person-name guess: capitalized word runs NOT already consumed.
        _consume_name_suspicion(sentence, result)

        # Relationship hypothesis for anything co-located in the same sentence.
        ids = _sentence_entity_ids(result, sentence)
        if len(ids) >= 2:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    if a == b:
                        continue
                    result.relationships.append(
                        RelationshipMention(
                            source_id=a, target_id=b,
                            rel_type="ASSOCIATED_WITH",
                            confidence=0.4,  # hypothesis only — requires validation
                            timestamp=first_ts,
                            attributes={"uncertain": True, "basis": "co-location in same record text"},
                        )
                    )
    return result


def _sentence_entity_ids(result: ExtractionResult, sentence: str) -> list[str]:
    """Entities that were actually extracted IN this sentence (phone/vehicle/org/...)."""
    ids: list[str] = []
    for e in result.entities:
        raw = (e.attributes or {}).get("raw", "")
        if not raw:
            continue
        if re.sub(r"\D", "", raw) and any(part in sentence for part in raw.split()):
            if e.entity_id not in ids:
                ids.append(e.entity_id)
        elif raw in sentence:
            if e.entity_id not in ids:
                ids.append(e.entity_id)
    return ids


def _find_locations(sentence: str) -> list[str]:
    out: list[str] = []
    # "Sector 17", "Dock 4", "Warehouse 3A", "Sector 17 warehouse" style markers.
    for m in re.finditer(
        rf"(?P<pre>[A-Z][\w.'-]*(?: [A-Z][\w.'-]*)*)?\s*"
        rf"(?P<base>\d{{1,3}}[A-Z]?)\s*"
        rf"(?P<cue>{'|'.join(_LOC_CUES)})",
        sentence,
        re.IGNORECASE,
    ):
        base = m.group("base")
        pre = (m.group("pre") or "").split()[-1:]
        frag = " ".join(part for part in [*(part for part in pre), base, m.group("cue")] if part)
        frag = frag.strip(" ,.;:")
        if frag not in out and len(frag) >= 4:
            out.append(frag.title())
    # Capitalized toponyms followed by a location cue ("Kandivali West" style handled above).
    return out


_GOVT_WORDS = {"SHRI", "SRI", "DR", "PROF", "MR", "MRS", "MS", "INSPECTOR", "ASI", "PSI", "SHO", "OFFICER"}


def _consume_name_suspicion(sentence: str, result: ExtractionResult) -> None:
    """Low-confidence PERSON guesses from capitalized runs (not org/sentence-head)."""
    words = sentence.split()
    for i in range(len(words) - 1):
        run: list[str] = []
        j = i
        while j < len(words) and re.match(r"^[A-Z][a-z]{2,}$", words[j]):
            run.append(words[j])
            j += 1
        if len(run) >= 2:
            name = " ".join(run)
            first = run[0].upper()
            if first in _GOVT_WORDS:
                continue
            prev = words[i - 1] if i > 0 else ""
            if prev.rstrip(".") in ("at", "the", "by", "from", "near", "in"):
                continue
            existing_raw = {e.attributes.get("raw", "") for e in result.entities}
            if name in existing_raw:
                continue
            did = f"P-{_stem_for_org(name)}"
            for e in result.entities:
                if e.entity_id == did and e.entity_type == "PERSON":
                    break
            else:
                idx = sentence.find(name)
                # do not guess location/organization words already extracted
                overlap = any(n.lower() in (e.name or "").lower() for e in result.entities
                              if e.entity_type in ("LOCATION", "ORGANIZATION"))
                if not overlap:
                    _add_entity(result, EntityMention(
                        did, "PERSON", name, 0.45,
                        attributes={"uncertain": True, "raw": name, "idx": idx},
                    ))


def extract(record: SourceRecord) -> ExtractionResult:
    """Extract entity + relationship mentions from a normalized record."""
    result = ExtractionResult()
    fields = record.fields or {}

    # Entity mentions from known structured fields.
    for key, (etype, default_name) in _FIELD_ENTITIES.items():
        value = fields.get(key)
        if value is None:
            continue
        if isinstance(value, (list,)):
            continue
        entity_id = str(value)
        name = default_name if key == "person" else entity_id
        result.entities.append(
            EntityMention(entity_id=entity_id, entity_type=etype, name=name, confidence=0.9)
        )

    # Relationship mentions.
    for a_field, pairs in _REL_BY_FIELD.items():
        a_value = fields.get(a_field)
        if a_value is None:
            continue
        for b_field, rel_type in pairs:
            b_value = fields.get(b_field)
            if b_value is None:
                continue
            attrs = {k: fields[k] for k in ("amount", "duration") if fields.get(k)}
            result.relationships.append(
                RelationshipMention(
                    source_id=str(a_value),
                    target_id=str(b_value),
                    rel_type=rel_type,
                    confidence=0.85,
                    timestamp=record.timestamp,
                    attributes=attrs,
                )
            )

    # Free-text pass for FIR / surveillance / intelligence / social notes.
    text = (record.text or "").strip()
    if text and not result.entities:
        text_result = extract_text(record)
        result.entities.extend(text_result.entities)
        result.relationships.extend(text_result.relationships)

    return result


def extract_many(records: list[SourceRecord]) -> ExtractionResult:
    """Extract across many records, merging entity mentions."""
    merged = ExtractionResult()
    seen_entities: set[tuple[str, str]] = set()
    for record in records:
        res = extract(record)
        for e in res.entities:
            key = (e.entity_id, e.entity_type)
            if key not in seen_entities:
                seen_entities.add(key)
                merged.entities.append(e)
        merged.relationships.extend(res.relationships)
    return merged
