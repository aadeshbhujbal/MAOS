"""Secret and PHI redaction helpers (pure core).

This module provides pure functions that detect and redact sensitive data —
secrets, API keys, and Protected Health Information (PHI) — from dictionaries
before they are persisted to audit logs, transmitted in agent messages, or
passed to LLM providers (Req 5.6, 9.5).

**Design:**

* A constant :data:`PHI_MARKER_KEYS` defines a set of field-name patterns that
  indicate the value is sensitive (e.g., ``"password"``, ``"ssn"``,
  ``"diagnosis"``).
* :func:`redact` deep-copies a dict and replaces values whose keys match a
  marker pattern with the placeholder ``"[REDACTED]"``.  Handles nested dicts
  and lists of dicts recursively.
* :func:`contains_phi` returns ``True`` if any key in the (possibly nested)
  dict matches a PHI/secret marker, without modifying the input.

Both functions are **pure** — no I/O, no side effects, deterministic.
"""

from __future__ import annotations

import copy
from typing import Any

# ---------------------------------------------------------------------------
# Constant: marker key patterns that indicate PHI or secrets
# ---------------------------------------------------------------------------

PHI_MARKER_KEYS: set[str] = {
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "api_secret",
    "ssn",
    "social_security",
    "dob",
    "date_of_birth",
    "diagnosis",
    "prescription",
    "medical_record",
    "phi_",
    "access_token",
    "refresh_token",
    "private_key",
    "credit_card",
    "card_number",
    "cvv",
    "patient_name",
    "patient_id",
    "health_record",
    "insurance_id",
    "mrn",
}

_REDACTED_PLACEHOLDER: str = "[REDACTED]"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _key_matches_marker(key: str, marker_keys: set[str]) -> bool:
    """Return True if *key* matches any marker pattern.

    Matching is case-insensitive and uses substring containment — a key
    matches if any marker string is contained within the lowered key.
    This covers both exact matches (``"password"`` matching ``"password"``)
    and prefix/infix patterns (``"phi_"`` matching ``"phi_data"``).
    """
    lower_key = key.lower()
    return any(marker in lower_key for marker in marker_keys)


def _redact_value(value: Any, marker_keys: set[str]) -> Any:
    """Recursively redact sensitive values within nested structures."""
    if isinstance(value, dict):
        return _redact_dict(value, marker_keys)
    if isinstance(value, list):
        return [_redact_value(item, marker_keys) for item in value]
    return value


def _redact_dict(data: dict[str, Any], marker_keys: set[str]) -> dict[str, Any]:
    """Redact values in a dict whose keys match a marker pattern."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if _key_matches_marker(key, marker_keys):
            result[key] = _REDACTED_PLACEHOLDER
        else:
            result[key] = _redact_value(value, marker_keys)
    return result


def _contains_phi_recursive(data: Any, marker_keys: set[str]) -> bool:
    """Check recursively whether any key in the structure matches a marker."""
    if isinstance(data, dict):
        for key, value in data.items():
            if _key_matches_marker(key, marker_keys):
                return True
            if _contains_phi_recursive(value, marker_keys):
                return True
    elif isinstance(data, list):
        for item in data:
            if _contains_phi_recursive(item, marker_keys):
                return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact(
    data: dict[str, Any],
    *,
    marker_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Deep-copy *data* and replace sensitive values with ``"[REDACTED]"``.

    A value is considered sensitive if its key matches any pattern in
    *marker_keys* (defaults to :data:`PHI_MARKER_KEYS`).  Matching is
    case-insensitive substring containment.

    Nested dicts and lists of dicts are handled recursively — the function
    walks the entire structure.

    This is a **pure function**: the original *data* is never mutated.

    Args:
        data: The dictionary to redact.  Must be a dict (not a list or scalar).
        marker_keys: Optional override set of marker patterns.  When ``None``,
            :data:`PHI_MARKER_KEYS` is used.

    Returns:
        A new dict with sensitive values replaced by ``"[REDACTED]"``.

    Example::

        >>> redact({"user": "alice", "password": "s3cr3t"})
        {'user': 'alice', 'password': '[REDACTED]'}
    """
    effective_markers = marker_keys if marker_keys is not None else PHI_MARKER_KEYS
    # We perform our own recursive copy+redact rather than copy.deepcopy first,
    # because _redact_dict already produces a new dict tree.  However, leaf
    # values that are mutable objects (other than dict/list) still reference
    # the originals — use deepcopy on the input to guarantee full isolation.
    safe_data: dict[str, Any] = copy.deepcopy(data)
    return _redact_dict(safe_data, effective_markers)


def contains_phi(
    data: dict[str, Any],
    *,
    marker_keys: set[str] | None = None,
) -> bool:
    """Return ``True`` if any key in *data* matches a PHI/secret marker.

    Walks nested dicts and lists recursively.  Does **not** modify *data*.

    Args:
        data: The dictionary to inspect.
        marker_keys: Optional override set of marker patterns.  When ``None``,
            :data:`PHI_MARKER_KEYS` is used.

    Returns:
        ``True`` if at least one key matches a marker pattern, else ``False``.

    Example::

        >>> contains_phi({"user": "alice", "ssn": "123-45-6789"})
        True
        >>> contains_phi({"user": "alice", "email": "a@b.com"})
        False
    """
    effective_markers = marker_keys if marker_keys is not None else PHI_MARKER_KEYS
    return _contains_phi_recursive(data, effective_markers)
