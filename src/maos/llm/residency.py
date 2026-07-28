"""Data_Residency_Policy — PHI-aware provider filtering (Req 8.4, 8.7, TC-4).

Pure configuration module with no I/O. The ``DataResidencyPolicy`` holds two
ordered provider chains (non-PHI and PHI) and exposes query methods that the
``LLM_Provider_Adapter`` and ``ContextHandoffManager`` use to determine which
providers may receive a given call.

Design decision 11 defines the concrete chains:
- **Non-PHI (ordered):** Anthropic Claude → Google Gemini → OpenAI →
  Amazon Bedrock (Claude) → Google Vertex (Gemini).
- **PHI-bearing (BAA-only, ordered):** Amazon Bedrock (Claude, BAA) →
  Google Vertex (Gemini, BAA) → self-hosted model.

PHI calls NEVER see non-eligible entries (Req 8.4, Property 26, Property 52).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderEntry:
    """A single provider+model entry in the fallback chain.

    Attributes:
        provider: Logical provider name (e.g. ``"anthropic"``, ``"bedrock"``).
        model: Concrete model identifier (e.g. ``"claude-sonnet-4-20250514"``).
        phi_eligible: Whether this entry may receive PHI (BAA-covered host).
    """

    provider: str
    model: str
    phi_eligible: bool


class DataResidencyPolicy:
    """Residency-aware provider chain filter (Req 8.4, 8.7, TC-4).

    Holds two ordered lists of ``ProviderEntry``:
    - ``non_phi_chain``: the full fallback chain for calls that do NOT contain PHI.
    - ``phi_chain``: the restricted fallback chain for calls that contain PHI;
      every entry in this list has ``phi_eligible == True``.

    Invariant: no entry with ``phi_eligible == False`` ever appears in
    ``phi_chain``. This is enforced at construction time.
    """

    def __init__(
        self,
        non_phi_chain: list[ProviderEntry],
        phi_chain: list[ProviderEntry],
    ) -> None:
        # Validate invariant: PHI chain must only contain eligible entries.
        for entry in phi_chain:
            if not entry.phi_eligible:
                raise ValueError(
                    f"PHI chain must not contain non-eligible entries: "
                    f"{entry.provider}/{entry.model}"
                )
        self._non_phi_chain: list[ProviderEntry] = list(non_phi_chain)
        self._phi_chain: list[ProviderEntry] = list(phi_chain)

    @property
    def non_phi_chain(self) -> list[ProviderEntry]:
        """Ordered fallback chain for non-PHI calls."""
        return list(self._non_phi_chain)

    @property
    def phi_chain(self) -> list[ProviderEntry]:
        """Ordered fallback chain for PHI-bearing calls (BAA-only)."""
        return list(self._phi_chain)

    def permitted_providers(self, contains_phi: bool) -> list[ProviderEntry]:
        """Return the ordered provider chain permitted for the given PHI flag.

        If ``contains_phi`` is True, returns only the PHI-eligible chain
        (Req 8.4: PHI calls resolve only to BAA-covered hosts).
        Otherwise returns the full non-PHI chain.
        """
        if contains_phi:
            return list(self._phi_chain)
        return list(self._non_phi_chain)

    def is_permitted(
        self, provider: str, model: str, contains_phi: bool
    ) -> bool:
        """Check whether a specific provider+model is in the permitted chain.

        Returns True iff the (provider, model) pair exists in the chain
        returned by ``permitted_providers(contains_phi)``.
        """
        chain = self._phi_chain if contains_phi else self._non_phi_chain
        return any(
            entry.provider == provider and entry.model == model
            for entry in chain
        )


def default_residency_policy() -> DataResidencyPolicy:
    """Create the default ``DataResidencyPolicy`` per design decision 11.

    Non-PHI chain (ordered):
        1. Anthropic Claude (primary, Req 8.2)
        2. Google Gemini
        3. OpenAI
        4. Amazon Bedrock (Claude)
        5. Google Vertex (Gemini)

    PHI-bearing chain (BAA-only, ordered):
        1. Amazon Bedrock (Claude, BAA region)
        2. Google Vertex (Gemini, BAA region)
        3. Self-hosted model
    """
    non_phi_chain = [
        ProviderEntry(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            phi_eligible=False,
        ),
        ProviderEntry(
            provider="gemini",
            model="gemini-2.5-pro",
            phi_eligible=False,
        ),
        ProviderEntry(
            provider="openai",
            model="gpt-4o",
            phi_eligible=False,
        ),
        ProviderEntry(
            provider="bedrock",
            model="anthropic.claude-sonnet-4-20250514-v1:0",
            phi_eligible=True,
        ),
        ProviderEntry(
            provider="vertex",
            model="gemini-2.5-pro",
            phi_eligible=True,
        ),
    ]

    phi_chain = [
        ProviderEntry(
            provider="bedrock",
            model="anthropic.claude-sonnet-4-20250514-v1:0",
            phi_eligible=True,
        ),
        ProviderEntry(
            provider="vertex",
            model="gemini-2.5-pro",
            phi_eligible=True,
        ),
        ProviderEntry(
            provider="self-hosted",
            model="llama-3-70b",
            phi_eligible=True,
        ),
    ]

    return DataResidencyPolicy(
        non_phi_chain=non_phi_chain,
        phi_chain=phi_chain,
    )
