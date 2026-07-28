"""Working_Memory checkpointer wrapping the LangGraph Postgres persistence.

This module configures the ``langgraph-checkpoint-postgres`` async saver so
that orchestration state is keyed by ``task_id`` (LangGraph ``thread_id``) and
carries ``tenant_id`` + ``mode`` metadata for isolation across resume.

The underlying package handles table creation/migration; this wrapper adds the
MAOS-specific keying, metadata convention, and a thin ``save``/``latest``
interface consumed by the orchestration graphs and the Context_Handoff manager.

Requirements: 7.6, 7.7, 14.3.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore[import-untyped]

from maos.config.settings import PostgresSettings


class MAOSCheckpointer:
    """MAOS wrapper around the LangGraph async Postgres checkpointer.

    Responsibilities:
    - Accept a Postgres DSN from ``PostgresSettings``.
    - Key checkpoints by ``task_id`` (mapped to LangGraph's ``thread_id``).
    - Carry ``tenant_id`` and ``mode`` as checkpoint metadata so that tenant
      and mode isolation survive resume across workers (Req 7.7, 9.2).
    - Expose ``save`` / ``latest`` for Working_Memory persistence and resume.

    The LangGraph ``AsyncPostgresSaver`` handles connection pooling, schema
    creation, and internal versioning of checkpoint blobs.
    """

    def __init__(self, dsn: str) -> None:
        """Initialize the checkpointer with a Postgres DSN.

        Parameters
        ----------
        dsn:
            Async-capable Postgres DSN (from ``PostgresSettings.dsn``).
        """
        self._dsn = dsn
        self._saver: AsyncPostgresSaver | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Create the underlying saver and ensure checkpoint tables exist.

        Must be called once at service startup before any ``save``/``latest``
        calls (e.g. during the FastAPI lifespan event).
        """
        self._saver = AsyncPostgresSaver.from_conn_string(self._dsn)
        await self._saver.setup()

    async def close(self) -> None:
        """Release resources held by the underlying saver."""
        # AsyncPostgresSaver does not expose an explicit close; this hook is
        # provided for forward-compatibility if one is added.
        self._saver = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save(
        self,
        task_id: str,
        state: dict[str, Any],
        *,
        tenant_id: str,
        mode: str,
    ) -> None:
        """Persist the Working_Memory checkpoint for a task (Req 7.6).

        Parameters
        ----------
        task_id:
            Unique task identifier, used as LangGraph's ``thread_id``.
        state:
            The current orchestration state dictionary to persist.
        tenant_id:
            Clinic scope — stored as metadata for isolation on resume.
        mode:
            ``DEVELOPMENT`` or ``RUNTIME`` — stored as metadata so the mode
            survives process restarts and worker migration.
        """
        if self._saver is None:
            raise RuntimeError(
                "MAOSCheckpointer is not set up. Call setup() first."
            )

        config = {
            "configurable": {
                "thread_id": task_id,
            }
        }
        metadata: dict[str, Any] = {
            "tenant_id": tenant_id,
            "mode": mode,
        }
        checkpoint = {
            "v": 1,
            "id": task_id,
            "ts": "",  # LangGraph fills the canonical timestamp
            "channel_values": state,
            "channel_versions": {},
            "versions_seen": {},
        }

        await self._saver.aput(config, checkpoint, metadata)

    async def latest(self, task_id: str) -> dict[str, Any] | None:
        """Return the most recently persisted state for resume (Req 7.7).

        Returns ``None`` when no checkpoint exists for the given ``task_id``,
        enabling callers to distinguish first-run from resume.

        Parameters
        ----------
        task_id:
            The task identifier whose latest checkpoint to retrieve.
        """
        if self._saver is None:
            raise RuntimeError(
                "MAOSCheckpointer is not set up. Call setup() first."
            )

        config = {
            "configurable": {
                "thread_id": task_id,
            }
        }

        checkpoint_tuple = await self._saver.aget_tuple(config)
        if checkpoint_tuple is None:
            return None

        checkpoint = checkpoint_tuple.checkpoint
        return checkpoint.get("channel_values")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_checkpointer(settings: PostgresSettings) -> MAOSCheckpointer:
    """Build a ``MAOSCheckpointer`` from application settings.

    The caller is responsible for calling ``await checkpointer.setup()``
    before use and ``await checkpointer.close()`` on shutdown.

    Example (FastAPI lifespan)::

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            ckpt = create_checkpointer(get_settings().postgres)
            await ckpt.setup()
            app.state.checkpointer = ckpt
            yield
            await ckpt.close()
    """
    return MAOSCheckpointer(dsn=settings.dsn)
