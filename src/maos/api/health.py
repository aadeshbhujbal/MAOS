"""Health and readiness probes (Req 10.6).

These are the ONLY unauthenticated endpoints on the FastAPI surface and expose
no tenant data. ``/healthz`` is a liveness probe (the process is up);
``/readyz`` is a readiness probe (the service is able to accept and process
Tasks). Dependency wiring for the readiness check is added in later tasks; for
now it reports a static ready state with no tenant-scoped detail.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    """Liveness/readiness response. Contains no tenant data."""

    status: str
    service: str


@router.get("/healthz", response_model=HealthStatus, summary="Liveness probe")
async def healthz() -> HealthStatus:
    """Report that the service process is alive."""
    return HealthStatus(status="ok", service="maos")


@router.get("/readyz", response_model=HealthStatus, summary="Readiness probe")
async def readyz() -> HealthStatus:
    """Report that the service is ready to accept and process Tasks.

    Later tasks extend this to verify downstream dependencies (Postgres, Redis,
    broker) before reporting ready.
    """
    return HealthStatus(status="ready", service="maos")
