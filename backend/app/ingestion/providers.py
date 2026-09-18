"""Provider seam for AI-assisted entity and relationship extraction.

The deterministic extractor is the safe local default. External NLP/LLM/OCR
providers can implement the same small contract without changing ingestion,
database persistence, graph materialization or analytics.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
import re

import httpx

from app.ingestion.extraction import ExtractionResult, extract, extract_many
from app.ingestion.extraction import EntityMention, RelationshipMention
from app.ingestion.records import SourceRecord
from app.core.config import get_settings


class ExtractionProvider(ABC):
    """Extract normalized intelligence from canonical source records."""

    name = "unknown"

    @abstractmethod
    def extract(self, records: list[SourceRecord]) -> ExtractionResult:
        """Return entity and relationship mentions with confidence scores."""


class DeterministicExtractionProvider(ExtractionProvider):
    """Local fallback used until an external AI provider is configured."""

    name = "deterministic"

    def extract(self, records: list[SourceRecord]) -> ExtractionResult:
        return extract_many(records)


class GeminiExtractionProvider(ExtractionProvider):
    """Gemini structured-output adapter for free-text and semi-structured data."""

    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def extract(self, records: list[SourceRecord]) -> ExtractionResult:
        merged = ExtractionResult()
        seen: set[tuple[str, str]] = set()
        for record in records:
            result = self._extract_record(record)
            for entity in result.entities:
                key = (entity.entity_id, entity.entity_type)
                if key not in seen:
                    seen.add(key)
                    merged.entities.append(entity)
            merged.relationships.extend(result.relationships)
        return merged

    def _extract_record(self, record: SourceRecord) -> ExtractionResult:
        prompt = {
            "task": "Extract investigative intelligence from one source record.",
            "rules": [
                "Return only facts supported by the supplied record.",
                "Do not infer guilt or invent identities.",
                "Use PERSON, LOCATION, VEHICLE, PHONE, ORGANIZATION, ACCOUNT or EVENT entity types.",
                "Use relationship types such as ASSOCIATED_WITH, LOCATED_AT, USED_VEHICLE, CALLED, TRANSFERRED_TO or MENTIONED_IN.",
                "Use the exact entity name from the record as name and a stable lowercase slug as entity_id.",
            ],
            "output": {
                "entities": [{"entity_id": "", "entity_type": "PERSON", "name": "", "confidence": 0.0}],
                "relationships": [{"source_id": "", "target_id": "", "rel_type": "", "confidence": 0.0}],
            },
            "source_type": record.source_type,
            "record_id": record.record_id,
            "timestamp": record.timestamp,
            "text": record.text,
            "fields": record.fields,
        }
        body = {
            "contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=True)}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        try:
            response = httpx.post(
                url,
                headers={"x-goog-api-key": self._api_key},
                json=body,
                timeout=30.0,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            return _parse_provider_output(text)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            # A rate-limited or unavailable optional AI provider must not make
            # otherwise valid structured intake data disappear from the map.
            return extract(record)


def get_extraction_provider(provider_name: str | None = None) -> ExtractionProvider:
    """Resolve a configured provider without making the prototype fragile."""
    # External providers will be registered here once credentials and an
    # agreed response schema are supplied. Unknown values fail safe locally.
    selected = (provider_name or "deterministic").lower()
    settings = get_settings()
    if settings.secret_env.lower() == "test":
        return DeterministicExtractionProvider()
    if selected == "gemini" and settings.gemini_api_key:
        return GeminiExtractionProvider(settings.gemini_api_key, settings.gemini_model)
    return DeterministicExtractionProvider()


def _parse_provider_output(raw: str) -> ExtractionResult:
    """Validate the model response before it can enter the graph."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    data = json.loads(cleaned)
    result = ExtractionResult()
    for item in data.get("entities", []):
        entity_id = str(item.get("entity_id") or _slug(item.get("name", "")))
        name = str(item.get("name", "")).strip()
        entity_type = str(item.get("entity_type", "OTHER")).upper().strip()
        if not entity_id or not name:
            continue
        result.entities.append(EntityMention(entity_id, entity_type, name, _confidence(item.get("confidence"))))
    for item in data.get("relationships", []):
        source = str(item.get("source_id", "")).strip()
        target = str(item.get("target_id", "")).strip()
        rel_type = str(item.get("rel_type", "MENTIONED_IN")).upper().strip()
        if source and target and source != target:
            result.relationships.append(RelationshipMention(source, target, rel_type, _confidence(item.get("confidence"))))
    return result


def _confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")[:128]
