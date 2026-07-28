"""Shared pytest configuration and fixtures for the MAOS test suite.

Registers and loads a default Hypothesis profile with ``max_examples=100`` (the
project-wide minimum for property tests, per the tasks-plan convention). The
profile can be overridden via the ``HYPOTHESIS_PROFILE`` environment variable
(e.g. ``ci`` for a heavier run).
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, settings

# Default profile used by every property test unless overridden.
settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# A heavier profile for CI / nightly runs.
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture
def app():  # type: ignore[no-untyped-def]
    """Return a freshly built FastAPI app instance for tests."""
    from maos.api.app import create_app

    return create_app()
