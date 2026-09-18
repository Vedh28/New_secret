"""V1 API route aggregator.

Mounts all version-1 routers under the /api/v1 prefix.
Phase 2: health wired; auth/criminals/cases/graph routers are registered and
gain endpoints in Phases 3-6.
"""
from fastapi import APIRouter

from app.api.v1 import (
    analysis,
    audit,
    auth,
    case_alerts,
    case_data,
    cases,
    criminals,
    dashboard,
    graph,
    health,
    integrity,
    intelligence,
    leads,
    reports,
    search,
    sources,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(criminals.router, prefix="/criminals", tags=["criminals"])
api_router.include_router(cases.router, prefix="/cases", tags=["cases"])
api_router.include_router(sources.router, prefix="/cases", tags=["sources"])
api_router.include_router(case_data.router, prefix="/cases", tags=["case-data"])
api_router.include_router(case_alerts.router, prefix="/cases", tags=["alerts"])
api_router.include_router(leads.router, prefix="/cases", tags=["leads"])
api_router.include_router(intelligence.router, prefix="/cases", tags=["intelligence"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(integrity.router, prefix="/integrity", tags=["integrity"])
