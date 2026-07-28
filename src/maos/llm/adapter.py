"""LLM_Provider_Adapter — sole entry point for all model calls (Req 8.1).

Implements the provider-agnostic adapter that:
- Selects a provider from the residency-permitted chain (Req 8.2, 8.4).
- Attempts the call with ordered fallback through the chain (Req 8.3).
- Records provider/model/tokens to the Cost_Meter on success (Req 8.5).
- Raises ``ProviderFailureError`` when all providers fail.

The actual provider call is delegated to the abstract ``_call_provider`` method,
which subclasses or test doubles override. The adapter itself owns the chain
logic, fallback iteration, and metering.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 15.4.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from maos.contracts.llm import LLMRequest, LLMResponse
from maos.llm.residency import DataResidencyPolicy, ProviderEntry

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProviderFailureError(Exception):
    """Raised when all providers in the permitted fallback chain have failed.

    Attributes:
        errors: Mapping of ``(provider, model)`` to the exception raised.
    """

    def __init__(
        self,
        errors: dict[tuple[str, str], Exception],
        message: str = "All permitted providers failed",
    ) -> None:
        self.errors = errors
        super().__init__(message)


# ---------------------------------------------------------------------------
# CostMeterProtocol — typing.Protocol for the Cost_Meter dependency
# ---------------------------------------------------------------------------


@runtime_checkable
class CostMeterProtocol(Protocol):
    """Protocol matching the Cost_Meter's ``record`` method (Req 8.5, 10.8)."""

    def record(
        self,
        *,
        agent_id: str,
        task_id: str,
        tenant_id: str,
        provider: str,
        model: str,
        tokens: int,
        cost_usd: float,
    ) -> None:
        """Record a completed model call's cost and token usage."""
        ...


# ---------------------------------------------------------------------------
# LLMProviderAdapter
# ---------------------------------------------------------------------------


class LLMProviderAdapter:
    """The SOLE entry point for all LLM model calls (Req 8.1).

    Constructor Parameters:
        residency_policy: A ``DataResidencyPolicy`` instance that determines the
            permitted provider chain based on ``contains_phi``.
        cost_meter: Any object satisfying ``CostMeterProtocol`` — used to record
            provider/model/tokens on each successful call (Req 8.5).

    Behavior:
        1. On ``complete(request)``, the adapter resolves the permitted provider
           chain from the residency policy using ``request.contains_phi``.
        2. It defaults to the first entry in the chain (Anthropic Claude for
           non-PHI calls, Req 8.2).
        3. On failure, it iterates through the remaining chain entries in order
           (ordered fallback, Req 8.3).
        4. If all entries fail, it raises ``ProviderFailureError``.
        5. On success, it records provider/model/tokens to the cost meter
           (Req 8.5) and returns the ``LLMResponse``.
    """

    def __init__(
        self,
        residency_policy: DataResidencyPolicy,
        cost_meter: CostMeterProtocol,
    ) -> None:
        self._residency_policy = residency_policy
        self._cost_meter = cost_meter

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a model call with residency-aware fallback (Req 8.1–8.5, 15.4).

        Selects the permitted provider chain based on ``request.contains_phi``,
        attempts each provider in order, and returns the first successful
        response. Records usage to the cost meter on success.

        Raises:
            ProviderFailureError: When all permitted providers fail.
        """
        chain = self._residency_policy.permitted_providers(request.contains_phi)

        if not chain:
            raise ProviderFailureError(
                errors={},
                message="No permitted providers configured for "
                f"contains_phi={request.contains_phi}",
            )

        errors: dict[tuple[str, str], Exception] = {}

        for entry in chain:
            try:
                response = await self._call_provider(entry, request)
            except Exception as exc:
                errors[(entry.provider, entry.model)] = exc
                continue

            # Success — record to cost meter (Req 8.5).
            self._cost_meter.record(
                agent_id="",  # Populated by the caller/graph node layer
                task_id="",   # Populated by the caller/graph node layer
                tenant_id=request.tenant_id,
                provider=response.provider,
                model=response.model,
                tokens=response.total_tokens,
                cost_usd=0.0,  # Actual cost computed by the Cost_Meter impl
            )

            return response

        # All providers failed (Req 8.3 exhaustion).
        raise ProviderFailureError(errors=errors)

    async def _call_provider(
        self, entry: ProviderEntry, request: LLMRequest
    ) -> LLMResponse:
        """Invoke a specific provider entry with the given request.

        This is a stub/abstract method that subclasses or test doubles
        override with actual provider SDK calls. The adapter itself handles
        the chain logic, fallback iteration, and metering.

        Raises:
            NotImplementedError: If not overridden by a subclass or test double.
        """
        raise NotImplementedError(
            f"_call_provider must be overridden to invoke "
            f"{entry.provider}/{entry.model}"
        )
