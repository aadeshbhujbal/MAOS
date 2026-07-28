"""Message_Bus delivery service over Redis Streams.

Implements the ``MessageBusService`` that delivers ``AgentMessage`` instances
between agents across the three-level hierarchy using Redis Streams as the
transport backend (task 23.1).

Responsibilities:
- Schema validation via :func:`~maos.messaging.codec.validate_message` before
  delivery (Req 6.2, 6.3). Invalid messages raise :class:`MessageValidationError`.
- Agent authentication: both sender and recipient must be registered in the
  :class:`~maos.registry.repository.AgentRegistryRepo` (Req 9.8).
  - Unknown sender → :exc:`UnregisteredAgentError`
  - Unknown recipient → :exc:`UnknownRecipientError` (Req 6.6)
- Serialization via :func:`~maos.messaging.codec.serialize_message` and
  publication to a Redis Stream keyed ``agent_messages:{recipient_id}``
  preserving trace identifiers (Req 6.4).

Requirements: 6.2, 6.3, 6.4, 6.6, 9.8.
"""

from __future__ import annotations

import redis.asyncio as redis

from maos.contracts.messaging import AgentMessage
from maos.messaging.codec import (
    serialize_message,
    validate_message,
)
from maos.registry.repository import AgentRegistryRepo

__all__ = [
    "MessageBusService",
    "UnknownRecipientError",
    "UnregisteredAgentError",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UnregisteredAgentError(Exception):
    """Raised when the sender is not registered in the Agent_Registry (Req 9.8).

    The Message_Bus authenticates every agent against the registry before
    allowing it to send messages.
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(
            f"Sender '{agent_id}' is not registered in the Agent_Registry."
        )


class UnknownRecipientError(Exception):
    """Raised when the recipient is not present in the Agent_Registry (Req 6.6).

    The Message_Bus returns this error to the sender without delivering the
    message.
    """

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(
            f"Recipient '{agent_id}' is not present in the Agent_Registry."
        )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MessageBusService:
    """Redis Streams–backed Message_Bus (Req 6.2, 6.3, 6.4, 6.6, 9.8).

    Parameters
    ----------
    redis_client:
        An async Redis client (``redis.asyncio.Redis``) used for stream
        publishing.
    registry:
        An :class:`~maos.registry.repository.AgentRegistryRepo` used to
        authenticate sender/recipient presence.
    """

    #: Redis key prefix for per-recipient message streams.
    STREAM_KEY_PREFIX: str = "agent_messages"

    def __init__(
        self,
        redis_client: redis.Redis,  # type: ignore[type-arg]
        registry: AgentRegistryRepo,
    ) -> None:
        self._redis = redis_client
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(self, msg: AgentMessage) -> None:
        """Validate, authenticate, and deliver an Agent_Message.

        Steps:
        1. Schema validation (Req 6.2, 6.3) — delegates to
           :func:`~maos.messaging.codec.validate_message`. If the message
           dict fails validation, :exc:`MessageValidationError` is raised
           and the message is NOT delivered.
        2. Sender authentication (Req 9.8) — verifies ``msg.sender_id`` is
           registered. If not, raises :exc:`UnregisteredAgentError`.
        3. Recipient authentication (Req 6.6, 9.8) — verifies
           ``msg.recipient_id`` is registered. If not, raises
           :exc:`UnknownRecipientError`.
        4. Serialization and publication — serializes via
           :func:`~maos.messaging.codec.serialize_message` and publishes to
           Redis Stream ``agent_messages:{recipient_id}`` preserving trace
           identifiers ``task_id``, ``subtask_id``, ``sub_subtask_id``
           (Req 6.4).

        Parameters
        ----------
        msg:
            The :class:`~maos.contracts.messaging.AgentMessage` to send.

        Raises
        ------
        MessageValidationError
            If the message fails schema validation.
        UnregisteredAgentError
            If the sender is not in the Agent_Registry.
        UnknownRecipientError
            If the recipient is not in the Agent_Registry.
        """
        # Step 1: Schema validation (Req 6.2, 6.3)
        # Re-validate against the schema to ensure the message is well-formed.
        # validate_message raises MessageValidationError on failure.
        validate_message(msg.model_dump(mode="python"))

        # Step 2: Authenticate sender (Req 9.8)
        sender_exists = await self._agent_exists(msg.sender_id)
        if not sender_exists:
            raise UnregisteredAgentError(msg.sender_id)

        # Step 3: Authenticate recipient (Req 6.6, 9.8)
        recipient_exists = await self._agent_exists(msg.recipient_id)
        if not recipient_exists:
            raise UnknownRecipientError(msg.recipient_id)

        # Step 4: Serialize and publish to Redis Stream (Req 6.4)
        payload_bytes = serialize_message(msg)
        stream_key = f"{self.STREAM_KEY_PREFIX}:{msg.recipient_id}"

        # Publish as a single field in the stream entry. The trace identifiers
        # (task_id, subtask_id, sub_subtask_id) are preserved in the serialized
        # payload and also included as top-level stream fields for indexing.
        await self._redis.xadd(
            stream_key,
            {
                "data": payload_bytes,
                "task_id": msg.task_id,
                "subtask_id": msg.subtask_id or "",
                "sub_subtask_id": msg.sub_subtask_id or "",
                "sender_id": msg.sender_id,
                "message_id": msg.message_id,
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _agent_exists(self, agent_id: str) -> bool:
        """Check whether an agent_id is present in the Agent_Registry.

        Performs a lightweight query against the registry's underlying store
        to determine registration status without fetching the full spec.
        """
        row = await self._registry._pool.fetch_one(
            "SELECT 1 FROM agent_registry WHERE subagent_id = %(agent_id)s LIMIT 1",
            {"agent_id": agent_id},
        )
        return row is not None
