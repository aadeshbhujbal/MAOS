"""Shared Hypothesis strategies for MAOS property tests.

This module is the single place where reusable generators for core domain
inputs live, so property tests across the suite stay consistent and constrain
generation to the valid input space. Concrete strategies for the Pydantic
contracts (Task / Subtask / Sub_Subtask, SubagentSpec, AgentMessage, ...) are
added alongside the tasks that introduce those models.

For now it provides small, broadly useful building blocks. Keep generators
smart: constrain to realistic, valid inputs rather than sampling the whole
type space.
"""

from __future__ import annotations

from hypothesis import strategies as st

# Identifier-like strings: non-empty, no surrounding whitespace, bounded length.
identifiers: st.SearchStrategy[str] = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=32,
)

# Non-empty human-readable text (e.g. titles, descriptions).
non_empty_text: st.SearchStrategy[str] = st.text(min_size=1, max_size=200).filter(
    lambda s: s.strip() != ""
)

# Positive budgets (reasoning steps, tool invocations, token budgets).
positive_budgets: st.SearchStrategy[int] = st.integers(min_value=1, max_value=1_000_000)


def operating_modes() -> st.SearchStrategy[str]:
    """Generate one of the two Agent_Operating_Mode values."""
    return st.sampled_from(["DEVELOPMENT", "RUNTIME"])


def platform_systems() -> st.SearchStrategy[str]:
    """Generate one of the three Platform_System values."""
    return st.sampled_from(["BACKEND", "WEB", "MOBILE"])
