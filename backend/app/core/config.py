"""Application settings loaded from environment / .env.

Phase 1: scaffolding. Values are read at import time; Phase 2 wires them into
SQLAlchemy and Neo4j drivers.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the SECRET backend."""

    # Application
    app_name: str = "SECRET API"
    secret_env: str = "dev"

    # PostgreSQL (local docker instance uses trust auth on 127.0.0.1)
    database_url: str = "postgresql+asyncpg://secret@localhost:5432/secret"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "secret"
    neo4j_connect_timeout: float = 3.0

    # JWT
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # Ingestion
    max_upload_bytes: int = 50_000_000
    extraction_provider: str = "deterministic"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"

    # Demo admin seed (dev only; override in production)
    admin_username: str = "admin"
    admin_password: str = "admin-secret"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
