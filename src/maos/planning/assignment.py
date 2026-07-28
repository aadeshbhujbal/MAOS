"""Agent assignment and effort estimation heuristics for the Planning Agent.

This module provides deterministic, keyword-based assignment of subtasks to
specialised agents and a heuristic effort estimator based on complexity
indicators in the subtask description.

- ``assign_agent`` — maps a subtask description to the best-fit agent role
  using domain-keyword matching (Req 11.3).  Returns a clarification request
  when no keywords match (Req 11.7).
- ``estimate_effort`` — classifies subtask complexity as small/medium/large
  based on description length, conjunction count, and presence of complexity
  signals (Req 11.6).
"""

from __future__ import annotations

import re
from typing import Literal

# ---------------------------------------------------------------------------
# Agent assignment keyword table (from design document)
# ---------------------------------------------------------------------------
# Each entry maps a set of domain keywords (case-insensitive) to an agent role.
# Order matters: first match wins.  Keywords are checked as whole-word
# boundaries so "log" doesn't accidentally match "login".
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: list[tuple[list[str], str]] = [
    (
        ["schema", "migration", "SQL", "index", "query"],
        "Database_Agent",
    ),
    (
        ["endpoint", "API", "service", "controller"],
        "Backend_Agent",
    ),
    (
        ["component", "page", "UI", "button", "form"],
        "Frontend_Agent",
    ),
    (
        ["deploy", "CI_CD", "CI/CD", "pipeline", "container"],
        "DevOps_Agent",
    ),
    (
        ["test", "coverage", "assertion", "E2E"],
        "QA_Agent",
    ),
    (
        ["auth", "permission", "vulnerability", "OWASP"],
        "Security_Agent",
    ),
    (
        ["metric", "alert", "dashboard", "log"],
        "Monitoring_Agent",
    ),
    (
        ["incident", "outage", "root_cause", "root cause", "recovery"],
        "Incident_Response_Agent",
    ),
    (
        ["cloud", "network", "load_balancer", "load balancer", "provision"],
        "Infrastructure_Agent",
    ),
    (
        ["model", "training", "dataset", "ML_pipeline", "ML pipeline"],
        "ML_AI_Agent",
    ),
    (
        ["design", "accessibility", "responsive", "UX"],
        "UI_UX_Agent",
    ),
    (
        ["OpenAPI", "versioning", "rate_limit", "rate limit", "swagger"],
        "API_Agent",
    ),
    (
        ["mobile", "Flutter", "iOS", "Android", "screen"],
        "Mobile_Agent",
    ),
    (
        ["docs", "README", "ADR", "changelog", "wiki"],
        "Documentation_Agent",
    ),
    (
        ["architecture", "scalability", "microservice"],
        "Architecture_Agent",
    ),
]

# Pre-compile regex patterns for each domain (case-insensitive).
_DOMAIN_PATTERNS: list[tuple[re.Pattern[str], str]] = []
for _keywords, _agent in _DOMAIN_KEYWORDS:
    # Build alternation of escaped keywords with word boundaries where
    # applicable.  Multi-word keywords (e.g. "root cause") and keywords
    # containing underscores use plain substring matching; single words use
    # \b boundaries.
    parts: list[str] = []
    for kw in _keywords:
        escaped = re.escape(kw)
        if " " in kw or "_" in kw:
            # Multi-word phrase or underscore identifier — match as literal
            parts.append(escaped)
        else:
            # Single word — use word boundaries
            parts.append(rf"\b{escaped}\b")
    pattern = re.compile("|".join(parts), re.IGNORECASE)
    _DOMAIN_PATTERNS.append((pattern, _agent))

# Clarification template returned when no domain keywords match (Req 11.7).
_CLARIFICATION_TEMPLATE = (
    "CLARIFICATION_NEEDED: Unable to determine the appropriate agent for this "
    "subtask. The description does not contain recognisable domain keywords. "
    "Please clarify: which domain does this subtask belong to? "
    "(e.g., database, backend, frontend, devops, testing, security, "
    "monitoring, incident response, infrastructure, ML/AI, UI/UX, API, "
    "mobile, documentation, architecture)"
)


def assign_agent(subtask_description: str) -> str:
    """Assign the most appropriate agent to a subtask based on domain keywords.

    Scans *subtask_description* against the domain-keyword table defined in the
    platform design document.  The first domain whose keywords appear in the
    description wins.

    If no keywords match, a clarification request string is returned describing
    the ambiguity and requesting more specific information (Req 11.7).

    Parameters
    ----------
    subtask_description:
        Free-text description of the subtask produced by the Planning Agent.

    Returns
    -------
    str
        The agent role name (e.g. ``"Database_Agent"``) when keywords match,
        or a clarification request string prefixed with
        ``"CLARIFICATION_NEEDED:"`` when no keywords match.

    Requirements: 11.3, 11.7
    """
    if not subtask_description or not subtask_description.strip():
        return _CLARIFICATION_TEMPLATE

    for pattern, agent in _DOMAIN_PATTERNS:
        if pattern.search(subtask_description):
            return agent

    return _CLARIFICATION_TEMPLATE


# ---------------------------------------------------------------------------
# Effort estimation heuristics
# ---------------------------------------------------------------------------
# Complexity indicators that push towards "large":
#   - Long descriptions (>120 chars)
#   - Multiple conjunctions / clauses ("and", "then", commas)
#   - Presence of high-complexity signals
# ---------------------------------------------------------------------------

_LARGE_SIGNALS: list[str] = [
    "refactor",
    "migrate",
    "redesign",
    "integrate",
    "end-to-end",
    "E2E",
    "cross-service",
    "distributed",
    "architecture",
    "scalability",
    "performance",
    "security audit",
    "compliance",
]

_MEDIUM_SIGNALS: list[str] = [
    "implement",
    "create",
    "build",
    "configure",
    "setup",
    "add",
    "update",
    "extend",
    "modify",
    "connect",
    "wire",
]

_LARGE_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(s)}\b" for s in _LARGE_SIGNALS),
    re.IGNORECASE,
)

_MEDIUM_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(s)}\b" for s in _MEDIUM_SIGNALS),
    re.IGNORECASE,
)


def estimate_effort(
    subtask_description: str,
) -> Literal["small", "medium", "large"]:
    """Estimate effort for a subtask based on complexity heuristics.

    The heuristic considers:
    - Description length (proxy for scope)
    - Number of conjunctions / clauses (proxy for multi-step work)
    - Presence of high-complexity signal words

    Parameters
    ----------
    subtask_description:
        Free-text description of the subtask.

    Returns
    -------
    Literal["small", "medium", "large"]
        Estimated effort bucket.

    Requirements: 11.6
    """
    desc = subtask_description.strip()
    if not desc:
        return "small"

    score = 0

    # Length-based scoring
    if len(desc) > 200:
        score += 3
    elif len(desc) > 120:
        score += 2
    elif len(desc) > 60:
        score += 1

    # Conjunction / clause counting (commas, "and", "then", semicolons)
    conjunctions = len(re.findall(r"\band\b|,|;|\bthen\b", desc, re.IGNORECASE))
    if conjunctions >= 4:
        score += 3
    elif conjunctions >= 2:
        score += 2
    elif conjunctions >= 1:
        score += 1

    # High-complexity signal words
    if _LARGE_PATTERN.search(desc):
        score += 3

    # Medium-complexity signal words (only if no large signals found)
    elif _MEDIUM_PATTERN.search(desc):
        score += 1

    # Classify
    if score >= 5:
        return "large"
    elif score >= 2:
        return "medium"
    return "small"
