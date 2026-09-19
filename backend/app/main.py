"""SECRET FastAPI application entrypoint.

Phase 2: wires the API router, adds health checks (app + DB + graph), and
manages engine/driver lifecycle on startup/shutdown.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401  (register models on Base.metadata)
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.core.neo4j import neo4j_connection
from app.models.user import User  # noqa: F401
from app.services.seed_service import ensure_admin_user

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup: best-effort demo admin seed (dev). Shutdown: close resources."""
    if settings.secret_env.lower() in {"dev", "demo"}:
        try:
            async with async_session_factory() as session:
                await ensure_admin_user(session)
        except Exception as exc:  # noqa: BLE001 - never block startup on seed failure
            import logging
            logging.getLogger("secret.startup").warning(
                "demo admin seed failed type=%s: %s", type(exc).__name__, exc)
    yield
    if settings.secret_env.lower() != "test":
        # Skip disposing the shared engine under tests: TestClient teardown
        # races with the Windows proactor loop and raises on the disposed pool.
        await engine.dispose()
    await neo4j_connection.close()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        description=(
            "Strategic Entity & Criminal Relationship Exploration Tool. "
            "All data is synthetic."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "health", "description": "Service, database and graph health"},
            {"name": "auth", "description": "Authentication (Phase 3)"},
            {"name": "criminals", "description": "Criminal / entity management (Phase 4)"},
            {"name": "cases", "description": "Case / investigation management (Phase 5)"},
            {"name": "graph", "description": "Relationship graph (Phase 6)"},
        ],
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix="/api/v1")

    @application.get("/health", tags=["health"], summary="Service health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name, "version": "0.2.0"}

    return application


app = create_app()
