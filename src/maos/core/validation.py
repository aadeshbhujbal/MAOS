"""Task input-contract validation (pure orchestration core).

This module implements the first step the Root_Orchestrator performs on a
submitted Task: validating it against the defined Task input contract and, when
the Task declares the capabilities it needs, checking that it can be mapped to
an available Platform_System or Subagent capability.

The logic here is **pure and deterministic** — it performs no I/O, holds no
state, and depends only on its arguments — so the correctness properties
(Property 2) are directly executable with Hypothesis.

What it provides:
- :func:`validate_task` — the single entry point. It returns a
  :class:`ValidationResult` tagged union that is exactly one of:
    * ``VALID``       — the submitted data is a well-formed :class:`Task`;
    * ``INVALID``     — the data violates the Task input contract, with one
                        :class:`FieldError` naming *each* failed field (Req 1.2);
    * ``UNSUPPORTED`` — the (otherwise valid) Task cannot be mapped to any
                        available capability, naming the missing capabilities
                        (Req 1.5).

Requirements:
- Req 1.1 — validate a submitted Task against the defined Task input contract.
- Req 1.2 — on failure, reject and return a descriptive error identifying
  *each* failed field.
- Req 1.5 — where a Task cannot be mapped to any available Platform_System or
  Subagent capability, return an unsupported-task error identifying the missing
  capability.

The Task input contract is the canonical :class:`maos.contracts.work_units.Task`
Pydantic model. A submitting Requester may optionally declare the capabilities a
Task needs inside its ``payload`` under two well-known keys:

- ``"target_platforms"`` — a list of Platform_System names (e.g. ``"BACKEND"``);
- ``"required_skills"``  — a list of Subagent Skill identifiers.

These declared capabilities are what Req 1.5 maps against the currently
available capabilities (:class:`AvailableCapabilities`). Capability mapping is
only performed when an ``available`` snapshot is supplied; structural contract
validation always runs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import ValidationError

from maos.contracts.work_units import PlatformSystem, Task

# Well-known payload keys through which a submitted Task declares the
# capabilities it needs. Kept as constants so callers and tests agree on them.
PAYLOAD_TARGET_PLATFORMS_KEY = "target_platforms"
PAYLOAD_REQUIRED_SKILLS_KEY = "required_skills"

__all__ = [
    "PAYLOAD_REQUIRED_SKILLS_KEY",
    "PAYLOAD_TARGET_PLATFORMS_KEY",
    "AvailableCapabilities",
    "FieldError",
    "TaskValidationError",
    "UnsupportedTaskError",
    "ValidationResult",
    "ValidationStatus",
    "check_supported",
    "validate_task",
    "validate_task_contract",
    "validate_task_input",
]


class ValidationStatus(str, Enum):
    """The outcome category of validating a submitted Task."""

    VALID = "valid"            # well-formed Task (Req 1.1)
    INVALID = "invalid"        # input-contract violation (Req 1.2)
    UNSUPPORTED = "unsupported"  # no mappable capability (Req 1.5)


@dataclass(frozen=True)
class FieldError:
    """A single input-contract violation, naming the field that failed (Req 1.2).

    ``field`` is the dotted path to the offending value (e.g. ``"title"`` or
    ``"auth_scope.0"``); ``message`` is the human-readable reason.
    """

    field: str
    message: str


class TaskValidationError(Exception):
    """Raised when a submitted Task fails input-contract validation (Req 1.2).

    Carries a list of :class:`FieldError` instances — one per failed field — so
    the caller can report exactly which parts of the submission are invalid.
    """

    def __init__(self, errors: list[FieldError]) -> None:
        self.errors: list[FieldError] = errors
        fields = ", ".join(e.field for e in errors)
        super().__init__(f"Task validation failed on field(s): {fields}")


class UnsupportedTaskError(Exception):
    """Raised when a Task's required capabilities cannot be matched (Req 1.5).

    The ``missing_capability`` attribute names the skill that no available
    Subagent provides.
    """

    def __init__(self, missing_capability: str) -> None:
        self.missing_capability: str = missing_capability
        super().__init__(
            f"Unsupported task: no available skill matches '{missing_capability}'"
        )


@dataclass(frozen=True)
class AvailableCapabilities:
    """Snapshot of capabilities a submitted Task may be mapped against (Req 1.5).

    Pure value object: the available Platform_Systems and the set of Skill
    identifiers currently offered by registered Subagents. Passing this snapshot
    to :func:`validate_task` enables the unsupported-task check; omitting it
    skips capability mapping (structural validation still runs).
    """

    platform_systems: frozenset[PlatformSystem] = field(default_factory=frozenset)
    skills: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(
        cls,
        platform_systems: Iterable[PlatformSystem] = (),
        skills: Iterable[str] = (),
    ) -> AvailableCapabilities:
        """Build a snapshot from any iterables of platforms and skill ids."""
        return cls(
            platform_systems=frozenset(platform_systems),
            skills=frozenset(skills),
        )


@dataclass(frozen=True)
class ValidationResult:
    """Tagged union describing the result of validating a submitted Task.

    Exactly one variant is populated according to ``status``:

    - ``VALID``       -> ``task`` is set; ``errors`` and ``missing_capabilities`` empty.
    - ``INVALID``     -> ``errors`` names each failed field (Req 1.2); ``task`` is None.
    - ``UNSUPPORTED`` -> ``missing_capabilities`` names the unmapped capabilities
                         (Req 1.5); ``task`` is None.

    Frozen and built only through the classmethods below so the variants stay
    mutually consistent and the type is safe to hash and compare in property tests.
    """

    status: ValidationStatus
    task: Task | None = None
    errors: tuple[FieldError, ...] = ()
    missing_capabilities: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        """True iff validation produced a well-formed, supported Task."""
        return self.status is ValidationStatus.VALID

    @property
    def failed_fields(self) -> tuple[str, ...]:
        """The dotted field paths that failed the contract (Req 1.2)."""
        return tuple(error.field for error in self.errors)

    @classmethod
    def valid(cls, task: Task) -> ValidationResult:
        """Build a ``VALID`` result wrapping the well-formed Task."""
        return cls(status=ValidationStatus.VALID, task=task)

    @classmethod
    def invalid(cls, errors: Iterable[FieldError]) -> ValidationResult:
        """Build an ``INVALID`` result carrying one error per failed field."""
        return cls(status=ValidationStatus.INVALID, errors=tuple(errors))

    @classmethod
    def unsupported(cls, missing_capabilities: Iterable[str]) -> ValidationResult:
        """Build an ``UNSUPPORTED`` result naming the unmapped capabilities."""
        return cls(
            status=ValidationStatus.UNSUPPORTED,
            missing_capabilities=tuple(missing_capabilities),
        )


def _format_location(location: tuple[Any, ...]) -> str:
    """Render a Pydantic error ``loc`` tuple as a dotted field path.

    Index components (list positions) are joined with dots too, so an error on
    the first element of ``auth_scope`` becomes ``"auth_scope.0"``. An empty
    location (a whole-model error, e.g. the input was not a mapping) renders as
    ``"__root__"``.
    """
    if not location:
        return "__root__"
    return ".".join(str(part) for part in location)


def _field_errors_from_validation_error(error: ValidationError) -> list[FieldError]:
    """Convert a Pydantic ``ValidationError`` into one FieldError per failure.

    Pydantic reports every failing location independently, so this names *each*
    failed field as Req 1.2 requires. Ordering follows Pydantic's deterministic
    report order, keeping the result reproducible for property tests.
    """
    return [
        FieldError(field=_format_location(detail["loc"]), message=detail["msg"])
        for detail in error.errors()
    ]


def validate_task_contract(submitted: Mapping[str, Any] | Any) -> ValidationResult:
    """Validate ``submitted`` against the Task input contract (Req 1.1, 1.2).

    Returns a ``VALID`` result wrapping the parsed :class:`Task` when the data
    conforms, otherwise an ``INVALID`` result naming each failed field. This
    performs no capability mapping; see :func:`validate_task` for the combined
    check.
    """
    try:
        task = Task.model_validate(submitted)
    except ValidationError as exc:
        return ValidationResult.invalid(_field_errors_from_validation_error(exc))
    return ValidationResult.valid(task)


def _requested_capabilities(task: Task) -> tuple[list[str], list[str]]:
    """Extract the platforms and skills a Task declares it needs (Req 1.5).

    Reads the optional ``target_platforms`` and ``required_skills`` lists from
    the Task ``payload``. Non-list values and non-string entries are ignored
    defensively; the structural contract already governs ``payload``'s type.
    """

    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item for item in value if isinstance(item, str)]

    payload = task.payload
    if not isinstance(payload, Mapping):
        return [], []
    platforms = _string_list(payload.get(PAYLOAD_TARGET_PLATFORMS_KEY))
    skills = _string_list(payload.get(PAYLOAD_REQUIRED_SKILLS_KEY))
    return platforms, skills


def _unmapped_capabilities(
    task: Task, available: AvailableCapabilities
) -> list[str]:
    """Return the capabilities a Task needs that no available capability covers.

    A Task is *supported* (empty result) when it declares no capabilities, or
    when at least one declared capability maps to the available snapshot — i.e.
    it can be routed somewhere (Req 1.5: "cannot be mapped to *any* available").
    When nothing maps, the returned list identifies every requested capability
    that is missing, each tagged ``platform:<name>`` or ``skill:<id>`` so the
    caller can report exactly what is unavailable.
    """
    requested_platforms, requested_skills = _requested_capabilities(task)
    if not requested_platforms and not requested_skills:
        return []

    available_platform_names = {ps.value for ps in available.platform_systems}

    missing: list[str] = []
    matched_any = False
    for platform in requested_platforms:
        if platform in available_platform_names:
            matched_any = True
        else:
            missing.append(f"platform:{platform}")
    for skill in requested_skills:
        if skill in available.skills:
            matched_any = True
        else:
            missing.append(f"skill:{skill}")

    # Supported as long as the Task can be mapped to at least one capability.
    if matched_any:
        return []
    return missing


def validate_task(
    submitted: Mapping[str, Any] | Any,
    available: AvailableCapabilities | None = None,
) -> ValidationResult:
    """Validate a submitted Task and, optionally, check capability mapping.

    Pure and deterministic. Resolution order:

    1. Validate ``submitted`` against the Task input contract. If it fails,
       return an ``INVALID`` result naming each failed field (Req 1.1, 1.2).
    2. If an ``available`` snapshot is supplied and the (now valid) Task declares
       capabilities that map to none of it, return an ``UNSUPPORTED`` result
       naming the missing capabilities (Req 1.5).
    3. Otherwise return a ``VALID`` result wrapping the parsed Task.

    Capability mapping is skipped entirely when ``available`` is ``None``, so the
    function doubles as a pure structural validator when no registry snapshot is
    available.
    """
    contract_result = validate_task_contract(submitted)
    if not contract_result.is_valid:
        return contract_result

    if available is None:
        return contract_result

    assert contract_result.task is not None  # VALID always carries a Task
    missing = _unmapped_capabilities(contract_result.task, available)
    if missing:
        return ValidationResult.unsupported(missing)
    return contract_result


# ---------------------------------------------------------------------------
# Imperative API: raise-on-failure wrappers (Req 1.1, 1.2, 1.5)
# ---------------------------------------------------------------------------


def validate_task_input(data: dict) -> Task:
    """Validate a raw dict against the Task Pydantic model (Req 1.1, 1.2).

    On success returns the validated :class:`Task` instance. On failure raises
    :class:`TaskValidationError` carrying a list of :class:`FieldError`
    instances — one per failed field — so the caller can report exactly which
    parts of the submission are invalid.

    This is a **pure function**: no I/O, no state; the result depends solely on
    ``data``.

    Args:
        data: The raw dictionary (e.g. from a deserialized JSON request body)
              representing a submitted Task.

    Returns:
        The validated :class:`~maos.contracts.work_units.Task` instance.

    Raises:
        TaskValidationError: When ``data`` does not conform to the Task input
            contract, carrying one :class:`FieldError` per failed field.
    """
    try:
        task = Task.model_validate(data)
    except ValidationError as exc:
        errors = _field_errors_from_validation_error(exc)
        raise TaskValidationError(errors) from exc
    return task


def check_supported(task: Task, available_skills: list[str]) -> None:
    """Check that a Task's required capabilities match available skills (Req 1.5).

    Inspects ``task.payload`` for a ``"required_skills"`` key containing a list
    of skill identifiers. Each declared skill is checked against
    ``available_skills``; if any is missing, raises :class:`UnsupportedTaskError`
    identifying the first missing capability.

    If the payload does not contain a ``"required_skills"`` key, the Task is
    considered supported (passes without raising).

    This is a **pure function**: no I/O, no state.

    Args:
        task: A validated Task whose payload may declare required skills.
        available_skills: The list of skill identifiers currently offered by
            registered Subagents.

    Raises:
        UnsupportedTaskError: When a required skill is not present in
            ``available_skills``.
    """
    payload = task.payload
    if not isinstance(payload, Mapping):
        return

    required = payload.get(PAYLOAD_REQUIRED_SKILLS_KEY)
    if not isinstance(required, (list, tuple)):
        return

    available_set = set(available_skills)
    for skill in required:
        if isinstance(skill, str) and skill not in available_set:
            raise UnsupportedTaskError(missing_capability=skill)
