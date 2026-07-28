"""LLM_Provider_Adapter request/response contracts.

Defines the provider-agnostic request (``LLMRequest``) submitted to the
LLM_Provider_Adapter and the normalized response (``LLMResponse``) it returns.
These are pure Pydantic v2 contracts; provider selection, residency routing, and
fallback logic live in the adapter.

Traceability:
- ``contains_phi`` drives Data_Residency_Policy routing to BAA-covered hosts
  (Req 8.4, TC-4).
- ``tenant_id`` scopes the call for isolation and cost attribution.
- ``LLMResponse`` carries ``provider``/``model`` and token usage so the
  Cost_Meter can record consumption per call (Req 8.5).
"""

from __future__ import annotations

from pydantic import BaseModel


class LLMRequest(BaseModel):
    """A provider-agnostic completion request (Req 8.1)."""

    messages: list[dict]
    model_hint: str | None = None
    contains_phi: bool = False         # gates residency routing (Req 8.4)
    tenant_id: str


class LLMResponse(BaseModel):
    """A normalized completion response with cost-metering fields (Req 8.5)."""

    provider: str                      # provider that served the call (Req 8.5)
    model: str                         # concrete model used (Req 8.5)
    content: str                       # generated output text
    prompt_tokens: int = 0             # tokens consumed by the prompt (Req 8.5)
    completion_tokens: int = 0         # tokens produced in the completion (Req 8.5)
    total_tokens: int = 0              # total tokens billed (Req 8.5, 15.5)
