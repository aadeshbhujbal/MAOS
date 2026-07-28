"""Cost_Meter persistence and aggregation.

Provides the ``CostMeterRepo`` class that records per-invocation cost entries
and exposes aggregation queries for budget enforcement and reporting.

Requirements: 8.5, 10.8, 15.5.
"""

from __future__ import annotations

from maos.memory.database import DatabasePool


class CostMeterRepo:
    """Repository wrapping ``DatabasePool`` for the ``cost_meter`` table.

    Each completed model invocation is recorded with provider, model, token
    count, and USD cost. Aggregation helpers support:

    - Per-Task token totals (used by the token-budget check before each model
      invocation — Req 15.5).
    - Per-Tenant daily token totals (daily ceiling checks).
    - Per-Agent cost totals (reporting and alerting — Req 10.8).
    """

    def __init__(self, pool: DatabasePool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def record(
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
        """Insert a cost entry into the ``cost_meter`` table.

        Called by the LLM_Provider_Adapter after every completed model
        invocation (Req 8.5, 10.8).
        """
        await self._pool.execute(
            """
            INSERT INTO cost_meter (
                agent_id, task_id, tenant_id, provider, model, tokens, cost_usd
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (agent_id, task_id, tenant_id, provider, model, tokens, cost_usd),
        )

    # ------------------------------------------------------------------
    # Aggregation queries
    # ------------------------------------------------------------------

    async def task_tokens(self, task_id: str) -> int:
        """Return the sum of tokens consumed for a given task.

        Used by the token-budget enforcement logic before each model
        invocation to decide whether the per-Task budget has been
        exhausted (Req 15.5).
        """
        row = await self._pool.fetch_one(
            "SELECT COALESCE(SUM(tokens), 0) AS total FROM cost_meter WHERE task_id = %s",
            (task_id,),
        )
        if row is None:
            return 0
        return int(row["total"])

    async def tenant_tokens_today(self, tenant_id: str) -> int:
        """Return the sum of tokens consumed by a tenant today (UTC).

        Used for daily ceiling checks to prevent runaway cost.
        """
        row = await self._pool.fetch_one(
            """
            SELECT COALESCE(SUM(tokens), 0) AS total
            FROM cost_meter
            WHERE tenant_id = %s
              AND recorded_at >= CURRENT_DATE
            """,
            (tenant_id,),
        )
        if row is None:
            return 0
        return int(row["total"])

    async def agent_cost(self, agent_id: str) -> float:
        """Return the total cost in USD for a given agent.

        Used for per-agent cost reporting and alerting (Req 10.8).
        """
        row = await self._pool.fetch_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM cost_meter WHERE agent_id = %s",
            (agent_id,),
        )
        if row is None:
            return 0.0
        return float(row["total"])
