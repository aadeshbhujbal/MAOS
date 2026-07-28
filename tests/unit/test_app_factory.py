"""Smoke tests for the FastAPI app factory and health/readiness probes.

Verifies the app factory builds and the two unauthenticated probes respond 200
with no tenant data (Req 10.6).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from maos.api.app import create_app


def test_create_app_builds_fastapi_instance() -> None:
    app = create_app()
    assert isinstance(app, FastAPI)
    # Settings are stashed for later dependency wiring.
    assert app.state.settings is not None


def test_healthz_returns_200() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "maos"
    # Health probe exposes no tenant data.
    assert "tenant" not in {k.lower() for k in body}


def test_readyz_returns_200() -> None:
    client = TestClient(create_app())
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["service"] == "maos"
    assert "tenant" not in {k.lower() for k in body}
