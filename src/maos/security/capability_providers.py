"""Mode-separation capability providers for MAOS.

Structural enforcement of Agent_Operating_Mode boundaries (Req 9.6, 9.7).

DEVELOPMENT-mode agents receive a SourceArtifactCapabilityProvider that permits
only repository/source-code operations and has NO accessor for live data.
RUNTIME-mode agents receive a RuntimeCapabilityProvider that permits only
live-domain operations and has NO accessor for repo/source resources.

Cross-mode operations are structurally impossible because the provider for a
given mode simply does not expose any interface to the other mode's resources.
Any attempt to act on a resource belonging to the opposite mode raises a
``ModeSeparationError``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from maos.contracts.work_units import OperatingMode

# ---------------------------------------------------------------------------
# Resource category constants
# ---------------------------------------------------------------------------

LIVE_DATA_RESOURCES: frozenset[str] = frozenset(
    {
        "appointments",
        "billing",
        "patients",
        "queue",
        "ehr",
        "vitals",
        "prescriptions",
        "lab_results",
        "insurance",
        "notifications",
        "clinical_notes",
        "care_plans",
    }
)
"""Resources belonging to the RUNTIME domain — live application data."""

SOURCE_RESOURCES: frozenset[str] = frozenset(
    {
        "repo.file",
        "repo.diff",
        "git",
        "code-exec",
        "lint",
        "test-runner",
        "build",
        "ci-pipeline",
        "static-analysis",
        "dependency-scan",
    }
)
"""Resources belonging to the DEVELOPMENT domain — repository/source artifacts."""


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class ModeSeparationError(Exception):
    """Raised when an agent attempts a cross-mode operation.

    Attributes:
        agent_mode: The OperatingMode of the agent that made the request.
        requested_resource: The resource category the agent tried to access.
        requested_action: The action the agent attempted on the resource.
    """

    def __init__(
        self,
        agent_mode: OperatingMode,
        requested_resource: str,
        requested_action: str,
    ) -> None:
        self.agent_mode = agent_mode
        self.requested_resource = requested_resource
        self.requested_action = requested_action
        super().__init__(
            f"Mode separation violation: agent in {agent_mode.value} mode "
            f"cannot perform '{requested_action}' on resource '{requested_resource}'"
        )


# ---------------------------------------------------------------------------
# Abstract capability provider
# ---------------------------------------------------------------------------


class CapabilityProvider(ABC):
    """Abstract base for mode-scoped capability providers.

    Each concrete provider restricts which resource categories are accessible
    and raises ``ModeSeparationError`` for disallowed cross-mode operations.
    """

    @property
    @abstractmethod
    def mode(self) -> OperatingMode:
        """The operating mode this provider enforces."""
        ...

    @abstractmethod
    def assert_allowed(self, resource: str, action: str) -> None:
        """Assert that *resource* + *action* is permitted under this mode.

        Args:
            resource: A resource category identifier (e.g. "patients", "repo.file").
            action: The action being attempted (e.g. "read", "write", "execute").

        Raises:
            ModeSeparationError: If the operation targets a resource outside
                this provider's mode scope.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class SourceArtifactCapabilityProvider(CapabilityProvider):
    """Capability provider for DEVELOPMENT-mode agents.

    Permits operations on repository/source resources only.
    Has NO live-data accessor — live PHI data stores are structurally excluded
    from the DEVELOPMENT agent's scope (Req 9.6).
    """

    @property
    def mode(self) -> OperatingMode:
        return OperatingMode.DEVELOPMENT

    def assert_allowed(self, resource: str, action: str) -> None:
        """Permit source operations; deny any live-data resource access."""
        if resource in LIVE_DATA_RESOURCES:
            raise ModeSeparationError(
                agent_mode=self.mode,
                requested_resource=resource,
                requested_action=action,
            )


class RuntimeCapabilityProvider(CapabilityProvider):
    """Capability provider for RUNTIME-mode agents.

    Permits operations on live domain resources only.
    Has NO repo/source accessor — source artifacts are structurally excluded
    from the RUNTIME agent's scope (Req 9.7).
    """

    @property
    def mode(self) -> OperatingMode:
        return OperatingMode.RUNTIME

    def assert_allowed(self, resource: str, action: str) -> None:
        """Permit live-domain operations; deny any repo/source resource access."""
        if resource in SOURCE_RESOURCES:
            raise ModeSeparationError(
                agent_mode=self.mode,
                requested_resource=resource,
                requested_action=action,
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_capability_provider(mode: OperatingMode) -> CapabilityProvider:
    """Return the correct capability provider for the given operating mode.

    Args:
        mode: The operating mode to obtain a provider for.

    Returns:
        A ``SourceArtifactCapabilityProvider`` for DEVELOPMENT mode, or a
        ``RuntimeCapabilityProvider`` for RUNTIME mode.

    Raises:
        ValueError: If an unrecognised mode is provided.
    """
    if mode is OperatingMode.DEVELOPMENT:
        return SourceArtifactCapabilityProvider()
    if mode is OperatingMode.RUNTIME:
        return RuntimeCapabilityProvider()
    raise ValueError(f"Unknown operating mode: {mode!r}")
