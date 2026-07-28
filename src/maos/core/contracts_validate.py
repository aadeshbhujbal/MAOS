"""Output-contract validation for Sub_Subtask results (Req 4.7).

This module provides a pure validation function that checks whether a
Sub_Subtask result dict conforms to the matched Skill's ``output_contract``
(a JSON Schema stored as a plain dict).

The validation is intentionally simple and does not depend on the external
``jsonschema`` library.  It checks:

1. **Required fields** — if the contract has a ``"required"`` key (list of
   field names), every listed field must be present in the result.
2. **Property types** — if the contract has a ``"properties"`` key (mapping
   field name → sub-schema), for each field that *is* present in the result,
   the value's Python type must match the ``"type"`` declared in that field's
   sub-schema.

If any violation is found, an :class:`OutputContractViolationError` is raised
carrying the list of human-readable violation strings and the originating
``skill_id``.
"""

from __future__ import annotations

from maos.contracts.agents import Skill

# Mapping from JSON Schema type strings to Python built-in types.
_JSON_SCHEMA_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


class OutputContractViolationError(Exception):
    """Raised when a Sub_Subtask result violates the Skill's output contract."""

    def __init__(self, violations: list[str], skill_id: str) -> None:
        self.violations = violations
        self.skill_id = skill_id
        summary = "; ".join(violations)
        super().__init__(
            f"Output contract violation for skill '{skill_id}': {summary}"
        )


def validate_output(result: dict, skill: Skill) -> None:
    """Validate *result* against *skill*'s output_contract.

    Parameters
    ----------
    result:
        The Sub_Subtask result dictionary to validate.
    skill:
        The matched Skill whose ``output_contract`` defines the expected schema.

    Raises
    ------
    OutputContractViolationError
        If *result* does not conform to the contract.
    """
    contract: dict = skill.output_contract
    violations: list[str] = []

    # 1. Check required fields
    required: list[str] = contract.get("required", [])
    for field_name in required:
        if field_name not in result:
            violations.append(f"missing required field '{field_name}'")

    # 2. Check property types for present fields
    properties: dict = contract.get("properties", {})
    for field_name, field_schema in properties.items():
        if field_name not in result:
            continue
        expected_type_str: str | None = field_schema.get("type") if isinstance(field_schema, dict) else None
        if expected_type_str is None:
            continue
        expected_type = _JSON_SCHEMA_TYPE_MAP.get(expected_type_str)
        if expected_type is None:
            # Unknown type string — skip validation for this field.
            continue
        value = result[field_name]
        if not isinstance(value, expected_type):
            actual_type = type(value).__name__
            violations.append(
                f"field '{field_name}' expected type '{expected_type_str}' "
                f"but got '{actual_type}'"
            )

    if violations:
        raise OutputContractViolationError(violations=violations, skill_id=skill.skill_id)
