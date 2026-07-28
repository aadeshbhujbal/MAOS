"""Agent_Registry Postgres repository.

Implements the ``AgentRegistry`` interface over Postgres using the shared
:class:`~maos.memory.database.DatabasePool`.  Provides:

- ``register`` — inserts into ``agent_registry`` and ``skill`` tables; raises
  :exc:`DuplicateSkillError` if a skill_id already exists for the same role
  within the same platform_system (Req 13.2).
- ``remove`` — deletes from ``agent_registry`` (cascades to skills). After
  removal the agent is no longer routable (Req 13.3).
- ``available_agents`` — queries all agents with ``status='available'`` for a
  given platform (Req 13.4).
- ``select`` — fetches candidates from DB, then delegates to the pure
  ``select_subagent`` function for deterministic selection (Req 2.5).

Requirements: 2.5, 13.1, 13.2, 13.3, 13.4.
"""

from __future__ import annotations

import json
from typing import Any

from maos.contracts.agents import AgenticCapability, Skill, SubagentSpec
from maos.contracts.work_units import OperatingMode, PlatformSystem
from maos.core.selection import select_subagent
from maos.memory.database import DatabasePool


class DuplicateSkillError(Exception):
    """Raised when a skill_id already exists for the same role within the same platform_system."""

    def __init__(self, skill_id: str, role: str, platform_system: str) -> None:
        self.skill_id = skill_id
        self.role = role
        self.platform_system = platform_system
        super().__init__(
            f"Skill '{skill_id}' already exists for role '{role}' "
            f"in platform_system '{platform_system}'."
        )


class AgentRegistryRepo:
    """Postgres-backed Agent_Registry (Req 13.1, 13.2, 13.3, 13.4, 2.5).

    All queries use the shared :class:`DatabasePool` for PgBouncer-compatible
    connection pooling. The deterministic selection logic is delegated to the
    pure :func:`~maos.core.selection.select_subagent` function so the DB layer
    performs only data retrieval.
    """

    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # register (Req 13.1, 13.2)
    # ------------------------------------------------------------------

    async def register(self, spec: SubagentSpec) -> None:
        """Register a Subagent with its skills.

        Inserts into ``agent_registry`` and ``skill`` tables within a single
        transaction. Raises :exc:`DuplicateSkillError` if any declared skill_id
        already exists for the same role within the same platform_system.

        Parameters
        ----------
        spec:
            The complete Subagent specification to register.

        Raises
        ------
        DuplicateSkillError
            If a skill_id conflicts with an existing registration for the same
            role and platform_system.
        """
        async with self._pool.acquire() as conn:
            # Use an explicit transaction for atomicity.
            async with conn.transaction():
                # Pre-check: duplicate skill_id for same role+platform_system.
                for skill in spec.skills:
                    row = await (
                        await conn.execute(
                            """
                            SELECT s.skill_id
                            FROM skill s
                            JOIN agent_registry ar ON ar.subagent_id = s.subagent_id
                            WHERE s.skill_id = %(skill_id)s
                              AND ar.role = %(role)s
                              AND ar.platform_system = %(platform_system)s
                            LIMIT 1
                            """,
                            {
                                "skill_id": skill.skill_id,
                                "role": spec.role,
                                "platform_system": spec.platform_system.value,
                            },
                            prepare=False,
                        )
                    ).fetchone()
                    if row is not None:
                        raise DuplicateSkillError(
                            skill_id=skill.skill_id,
                            role=spec.role,
                            platform_system=spec.platform_system.value,
                        )

                # Insert into agent_registry.
                await conn.execute(
                    """
                    INSERT INTO agent_registry (
                        subagent_id, role, platform_system, mode,
                        capability, mcp_allow_list, status, selection_priority
                    ) VALUES (
                        %(subagent_id)s, %(role)s, %(platform_system)s, %(mode)s,
                        %(capability)s, %(mcp_allow_list)s, %(status)s, %(selection_priority)s
                    )
                    """,
                    {
                        "subagent_id": spec.subagent_id,
                        "role": spec.role,
                        "platform_system": spec.platform_system.value,
                        "mode": spec.mode.value,
                        "capability": json.dumps(spec.capability.model_dump()),
                        "mcp_allow_list": json.dumps(spec.mcp_allow_list),
                        "status": spec.status,
                        "selection_priority": spec.selection_priority,
                    },
                    prepare=False,
                )

                # Insert skills.
                for skill in spec.skills:
                    await conn.execute(
                        """
                        INSERT INTO skill (
                            skill_id, subagent_id, input_contract,
                            output_contract, operation_scope
                        ) VALUES (
                            %(skill_id)s, %(subagent_id)s, %(input_contract)s,
                            %(output_contract)s, %(operation_scope)s
                        )
                        """,
                        {
                            "skill_id": skill.skill_id,
                            "subagent_id": spec.subagent_id,
                            "input_contract": json.dumps(skill.input_contract),
                            "output_contract": json.dumps(skill.output_contract),
                            "operation_scope": json.dumps(skill.operation_scope),
                        },
                        prepare=False,
                    )

    # ------------------------------------------------------------------
    # remove (Req 13.3)
    # ------------------------------------------------------------------

    async def remove(self, subagent_id: str) -> None:
        """Remove a Subagent from the registry.

        Deletes the agent row from ``agent_registry``. The ``skill`` table
        rows are cascade-deleted via the FK relationship. After removal, the
        agent is no longer routable.

        Parameters
        ----------
        subagent_id:
            The unique identifier of the Subagent to remove.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            # Delete skills first (cascade may handle this, but explicit
            # for clarity and portability).
            await conn.execute(
                "DELETE FROM skill WHERE subagent_id = %(subagent_id)s",
                {"subagent_id": subagent_id},
                prepare=False,
            )
            await conn.execute(
                "DELETE FROM agent_registry WHERE subagent_id = %(subagent_id)s",
                {"subagent_id": subagent_id},
                prepare=False,
            )

    # ------------------------------------------------------------------
    # available_agents (Req 13.4)
    # ------------------------------------------------------------------

    async def available_agents(self, platform: PlatformSystem) -> list[SubagentSpec]:
        """Return all agents with status='available' for the given platform.

        Queries ``agent_registry`` joined with ``skill`` to reconstruct the
        full :class:`SubagentSpec` for each available agent.

        Parameters
        ----------
        platform:
            The Platform_System to filter by.

        Returns
        -------
        list[SubagentSpec]
            All available Subagent specifications for the platform.
        """
        rows = await self._pool.fetch_all(
            """
            SELECT
                ar.subagent_id, ar.role, ar.platform_system, ar.mode,
                ar.capability, ar.mcp_allow_list, ar.status, ar.selection_priority
            FROM agent_registry ar
            WHERE ar.status = 'available'
              AND ar.platform_system = %(platform_system)s
            """,
            {"platform_system": platform.value},
        )

        specs: list[SubagentSpec] = []
        for row in rows:
            skills = await self._fetch_skills(row["subagent_id"])
            specs.append(self._row_to_spec(row, skills))
        return specs

    # ------------------------------------------------------------------
    # select (Req 2.5)
    # ------------------------------------------------------------------

    async def select(
        self,
        platform: PlatformSystem,
        skill_id: str,
        mode: OperatingMode,
    ) -> SubagentSpec | None:
        """Select a Subagent for routing using the deterministic selection rule.

        Fetches available candidates from the DB for the given platform, then
        delegates to :func:`~maos.core.selection.select_subagent` for
        deterministic selection (Req 2.5).

        Parameters
        ----------
        platform:
            The target Platform_System.
        skill_id:
            The required Skill identifier.
        mode:
            The required Agent_Operating_Mode.

        Returns
        -------
        SubagentSpec | None
            The selected Subagent, or ``None`` if no candidate matches.
        """
        candidates = await self.available_agents(platform)
        return select_subagent(candidates, platform, skill_id, mode)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_skills(self, subagent_id: str) -> list[Skill]:
        """Fetch all skills for a given subagent from the DB."""
        rows = await self._pool.fetch_all(
            """
            SELECT skill_id, input_contract, output_contract, operation_scope
            FROM skill
            WHERE subagent_id = %(subagent_id)s
            """,
            {"subagent_id": subagent_id},
        )
        return [
            Skill(
                skill_id=row["skill_id"],
                input_contract=row["input_contract"],
                output_contract=row["output_contract"],
                operation_scope=row["operation_scope"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_spec(row: dict[str, Any], skills: list[Skill]) -> SubagentSpec:
        """Convert a DB row + skills list into a SubagentSpec."""
        return SubagentSpec(
            subagent_id=row["subagent_id"],
            role=row["role"],
            platform_system=PlatformSystem(row["platform_system"]),
            mode=OperatingMode(row["mode"]),
            skills=skills,
            capability=AgenticCapability(**row["capability"]),
            mcp_allow_list=row["mcp_allow_list"],
            status=row["status"],
            selection_priority=row["selection_priority"],
        )
