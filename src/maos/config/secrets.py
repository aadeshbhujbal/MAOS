"""Managed secrets loading for MAOS.

Loads credentials, API keys, and MCP_Server connection secrets from a managed
secrets source (Vault, AWS Secrets Manager, or environment variables for local
development) at runtime.  Secret values NEVER appear in logs, audit entries,
error messages, stdout, or stderr (Req 9.10, TC-13).

Usage:
    provider = get_secrets_provider()
    api_key = await provider.get_secret("ANTHROPIC_API_KEY")
    batch = await provider.get_secrets(["DB_PASSWORD", "REDIS_TOKEN"])
"""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SecretStr — redaction wrapper
# ---------------------------------------------------------------------------


class SecretStr:
    """A string wrapper that NEVER exposes its value through repr/str/logging.

    Use ``.get_secret_value()`` to retrieve the real value programmatically.
    This ensures secrets cannot leak through printing, logging, or error messages.
    """

    __slots__ = ("_secret_value",)

    def __init__(self, value: str) -> None:
        # Bypass our custom __setattr__ for initial assignment.
        object.__setattr__(self, "_secret_value", value)

    def get_secret_value(self) -> str:
        """Return the underlying secret value."""
        return object.__getattribute__(self, "_secret_value")  # type: ignore[no-any-return]

    def __repr__(self) -> str:
        return "SecretStr('**********')"

    def __str__(self) -> str:
        return "**********"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            return bool(
                object.__getattribute__(self, "_secret_value")
                == object.__getattribute__(other, "_secret_value")
            )
        return NotImplemented

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_secret_value"))

    def __len__(self) -> int:
        val: str = object.__getattribute__(self, "_secret_value")
        return len(val)

    def __bool__(self) -> bool:
        val: str = object.__getattribute__(self, "_secret_value")
        return bool(val)

    # Prevent accidental mutation.
    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("SecretStr is immutable")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("SecretStr is immutable")

    # Prevent pickling which could serialize the value.
    def __reduce__(self) -> str:
        raise TypeError("SecretStr cannot be pickled")


# ---------------------------------------------------------------------------
# SecretsProvider — abstract interface
# ---------------------------------------------------------------------------


class SecretsProvider(ABC):
    """Abstract base for secrets backends.

    All implementations must ensure that secret values are never written to
    stdout/stderr, log output, or error messages.
    """

    @abstractmethod
    async def get_secret(self, name: str) -> SecretStr:
        """Load a single secret by name.

        Raises:
            KeyError: If the secret does not exist in the backend.
        """
        ...

    @abstractmethod
    async def get_secrets(self, names: list[str]) -> dict[str, SecretStr]:
        """Load multiple secrets by name.

        Returns a dict mapping each requested name to its ``SecretStr`` value.

        Raises:
            KeyError: If any requested secret does not exist in the backend.
        """
        ...


# ---------------------------------------------------------------------------
# Cached mixin — TTL-based caching to avoid repeated network calls
# ---------------------------------------------------------------------------


class _CachedSecretsMixin:
    """Mixin providing in-memory TTL caching for loaded secrets."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._cache: dict[str, tuple[SecretStr, float]] = {}
        self._ttl_seconds = ttl_seconds

    def _get_cached(self, name: str) -> SecretStr | None:
        entry = self._cache.get(name)
        if entry is None:
            return None
        value, cached_at = entry
        if time.monotonic() - cached_at > self._ttl_seconds:
            del self._cache[name]
            return None
        return value

    def _set_cached(self, name: str, value: SecretStr) -> None:
        self._cache[name] = (value, time.monotonic())

    def clear_cache(self) -> None:
        """Manually invalidate the entire cache."""
        self._cache.clear()


# ---------------------------------------------------------------------------
# EnvSecretsProvider — local development (environment variables)
# ---------------------------------------------------------------------------


class EnvSecretsProvider(_CachedSecretsMixin, SecretsProvider):
    """Loads secrets from environment variables.

    Suitable for local development only.  In production, secrets should be
    sourced from Vault or a cloud KMS.
    """

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        _CachedSecretsMixin.__init__(self, ttl_seconds=ttl_seconds)

    async def get_secret(self, name: str) -> SecretStr:
        cached = self._get_cached(name)
        if cached is not None:
            return cached

        value = os.environ.get(name)
        if value is None:
            # NEVER log the secret name with its value.
            logger.debug("Secret '%s' not found in environment", name)
            raise KeyError(f"Secret '{name}' not found in environment variables")

        secret = SecretStr(value)
        self._set_cached(name, secret)
        logger.debug("Loaded secret '%s' from environment", name)
        return secret

    async def get_secrets(self, names: list[str]) -> dict[str, SecretStr]:
        result: dict[str, SecretStr] = {}
        for name in names:
            result[name] = await self.get_secret(name)
        return result


# ---------------------------------------------------------------------------
# VaultSecretsProvider — HashiCorp Vault (production)
# ---------------------------------------------------------------------------


class VaultSecretsProvider(_CachedSecretsMixin, SecretsProvider):
    """Loads secrets from HashiCorp Vault using the ``hvac`` client.

    Requires the ``secrets`` optional dependency group::

        pip install maos[secrets]

    Configuration via environment variables:
        - VAULT_ADDR: Vault server URL (default: http://127.0.0.1:8200)
        - VAULT_TOKEN: Authentication token for Vault
        - VAULT_MOUNT_POINT: KV v2 mount point (default: secret)
        - VAULT_SECRET_PATH: Path prefix within the mount (default: maos)
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        token: str | None = None,
        mount_point: str | None = None,
        secret_path: str | None = None,
        ttl_seconds: float = 300.0,
    ) -> None:
        _CachedSecretsMixin.__init__(self, ttl_seconds=ttl_seconds)
        self._url = url or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
        self._token = token or os.environ.get("VAULT_TOKEN", "")
        self._mount_point = mount_point or os.environ.get("VAULT_MOUNT_POINT", "secret")
        self._secret_path = secret_path or os.environ.get("VAULT_SECRET_PATH", "maos")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import hvac
            except ImportError as exc:
                raise ImportError(
                    "The 'hvac' package is required for VaultSecretsProvider. "
                    "Install with: pip install maos[secrets]"
                ) from exc
            self._client = hvac.Client(url=self._url, token=self._token)
        return self._client

    async def get_secret(self, name: str) -> SecretStr:
        cached = self._get_cached(name)
        if cached is not None:
            return cached

        client = self._get_client()
        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=self._secret_path,
                mount_point=self._mount_point,
            )
        except Exception:
            # Never include secret values in error messages.
            logger.error("Failed to read from Vault path '%s'", self._secret_path)
            raise KeyError(
                f"Secret '{name}' could not be loaded from Vault"
            ) from None

        data: dict[str, Any] = response.get("data", {}).get("data", {})
        if name not in data:
            raise KeyError(f"Secret '{name}' not found in Vault at path '{self._secret_path}'")

        raw_value = data[name]
        if not isinstance(raw_value, str):
            raw_value = str(raw_value)

        secret = SecretStr(raw_value)
        self._set_cached(name, secret)
        logger.debug("Loaded secret '%s' from Vault", name)
        return secret

    async def get_secrets(self, names: list[str]) -> dict[str, SecretStr]:
        # Vault KV v2 reads the whole path at once, so we can batch efficiently.
        client = self._get_client()
        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=self._secret_path,
                mount_point=self._mount_point,
            )
        except Exception:
            logger.error("Failed to read from Vault path '%s'", self._secret_path)
            raise KeyError(
                "Secrets could not be loaded from Vault"
            ) from None

        data: dict[str, Any] = response.get("data", {}).get("data", {})
        result: dict[str, SecretStr] = {}
        for name in names:
            if name not in data:
                raise KeyError(
                    f"Secret '{name}' not found in Vault at path '{self._secret_path}'"
                )
            raw_value = data[name]
            if not isinstance(raw_value, str):
                raw_value = str(raw_value)
            secret = SecretStr(raw_value)
            self._set_cached(name, secret)
            result[name] = secret

        logger.debug("Loaded %d secrets from Vault", len(names))
        return result


# ---------------------------------------------------------------------------
# AWSSecretsProvider — AWS Secrets Manager (cloud)
# ---------------------------------------------------------------------------


class AWSSecretsProvider(_CachedSecretsMixin, SecretsProvider):
    """Loads secrets from AWS Secrets Manager using ``boto3``.

    Requires the ``secrets`` optional dependency group::

        pip install maos[secrets]

    Configuration via environment variables:
        - AWS_REGION: AWS region for Secrets Manager (default: us-east-1)
        - AWS_SECRET_PREFIX: Prefix for secret names (default: maos/)
    """

    def __init__(
        self,
        *,
        region_name: str | None = None,
        secret_prefix: str | None = None,
        ttl_seconds: float = 300.0,
    ) -> None:
        _CachedSecretsMixin.__init__(self, ttl_seconds=ttl_seconds)
        self._region = region_name or os.environ.get("AWS_REGION", "us-east-1")
        self._prefix = secret_prefix or os.environ.get("AWS_SECRET_PREFIX", "maos/")
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "The 'boto3' package is required for AWSSecretsProvider. "
                    "Install with: pip install maos[secrets]"
                ) from exc
            self._client = boto3.client(
                "secretsmanager",
                region_name=self._region,
            )
        return self._client

    async def get_secret(self, name: str) -> SecretStr:
        cached = self._get_cached(name)
        if cached is not None:
            return cached

        client = self._get_client()
        secret_id = f"{self._prefix}{name}"
        try:
            response = client.get_secret_value(SecretId=secret_id)
        except Exception:
            # Never include the secret value in error messages.
            logger.error("Failed to retrieve secret '%s' from AWS Secrets Manager", name)
            raise KeyError(
                f"Secret '{name}' could not be loaded from AWS Secrets Manager"
            ) from None

        raw_value: str = response.get("SecretString", "")
        if not raw_value:
            raise KeyError(
                f"Secret '{name}' is empty or binary in AWS Secrets Manager"
            )

        secret = SecretStr(raw_value)
        self._set_cached(name, secret)
        logger.debug("Loaded secret '%s' from AWS Secrets Manager", name)
        return secret

    async def get_secrets(self, names: list[str]) -> dict[str, SecretStr]:
        result: dict[str, SecretStr] = {}
        for name in names:
            result[name] = await self.get_secret(name)
        return result


# ---------------------------------------------------------------------------
# Factory — selects provider based on SECRETS_BACKEND env var
# ---------------------------------------------------------------------------

# Default TTL for secret caching (seconds).
_DEFAULT_CACHE_TTL = 300.0


def get_secrets_provider(
    *,
    backend: str | None = None,
    ttl_seconds: float | None = None,
) -> SecretsProvider:
    """Return a secrets provider based on configuration.

    The provider is selected by the ``SECRETS_BACKEND`` environment variable
    (or the ``backend`` keyword argument). Supported values:

        - ``env`` (default): Load from environment variables (local dev)
        - ``vault``: Load from HashiCorp Vault
        - ``aws``: Load from AWS Secrets Manager

    Args:
        backend: Override for ``SECRETS_BACKEND`` env var.
        ttl_seconds: Override cache TTL (default 300s / 5 minutes).

    Returns:
        A configured ``SecretsProvider`` instance.
    """
    selected = backend if backend is not None else os.environ.get("SECRETS_BACKEND", "env")
    cache_ttl = ttl_seconds if ttl_seconds is not None else _DEFAULT_CACHE_TTL

    selected_lower = selected.lower().strip()

    if selected_lower == "env":
        logger.info("Using EnvSecretsProvider (environment variables)")
        return EnvSecretsProvider(ttl_seconds=cache_ttl)
    elif selected_lower == "vault":
        logger.info("Using VaultSecretsProvider (HashiCorp Vault)")
        return VaultSecretsProvider(ttl_seconds=cache_ttl)
    elif selected_lower == "aws":
        logger.info("Using AWSSecretsProvider (AWS Secrets Manager)")
        return AWSSecretsProvider(ttl_seconds=cache_ttl)
    else:
        raise ValueError(
            f"Unknown SECRETS_BACKEND: '{selected}'. "
            f"Supported values: 'env', 'vault', 'aws'"
        )
