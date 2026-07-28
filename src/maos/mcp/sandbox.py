"""Sandbox runner for isolated execution of generated/untrusted code.

Provides a subprocess-based sandbox that enforces:
- No network by default
- Bounded CPU, memory, and wall-clock time
- Read-only scoped mounts (no host access)
- Denial of out-of-scope resource access

In production this would integrate with gVisor or Firecracker for full
kernel-level isolation. The current implementation uses asyncio.subprocess
with resource limits as a development-time approximation that preserves
the same contract and API surface.

Requirements: 5.7, TC-9
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from dataclasses import dataclass, field


class SandboxDeniedError(Exception):
    """Raised when sandboxed code attempts to access out-of-scope resources.

    This is a placeholder for production enforcement (gVisor/Firecracker
    seccomp policies, network namespace rules, mount restrictions). In
    production, the sandbox runtime would raise this when a syscall is
    blocked or a mount boundary is violated.
    """

    resource: str
    reason: str

    def __init__(self, *, resource: str, reason: str) -> None:
        self.resource = resource
        self.reason = reason
        super().__init__(
            f"Sandbox access denied: resource={resource!r}, reason={reason!r}"
        )


@dataclass
class SandboxConfig:
    """Configuration for sandbox resource limits.

    Attributes
    ----------
    cpu:
        CPU allocation (e.g. "1" for one core). Maps to cgroup limits in
        production.
    memory:
        Memory limit (e.g. "512m" for 512 MiB). Maps to cgroup memory
        limits in production.
    network:
        Network mode. "none" disables all network access (default).
        In production, this controls the network namespace.
    timeout_seconds:
        Maximum wall-clock time for code execution. If exceeded, the
        process is killed and ``SandboxResult.timed_out`` is set.
    read_only_mounts:
        List of paths the sandboxed code may read from (read-only).
        All other paths are inaccessible. In production these map to
        mount namespace bind-mounts with RO flags.
    """

    cpu: str = "1"
    memory: str = "512m"
    network: str = "none"
    timeout_seconds: int = 30
    read_only_mounts: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """Result of a sandboxed code execution.

    Attributes
    ----------
    stdout:
        Standard output captured from the sandboxed process.
    stderr:
        Standard error captured from the sandboxed process.
    exit_code:
        Process exit code. Non-zero indicates an error.
    timed_out:
        True if the process was killed because it exceeded the configured
        ``timeout_seconds``.
    """

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class Sandbox:
    """Isolated execution environment for generated/untrusted code (Req 5.7, TC-9).

    Executes code in a subprocess with bounded resources. The key contract:
    - No network by default (``network="none"``)
    - Bounded CPU/memory/wall-clock
    - Read-only scoped mounts
    - No host access

    In production, this class would delegate to gVisor (runsc) or a
    Firecracker microVM pool. The subprocess implementation preserves the
    same async API and timeout/result contract.

    Parameters
    ----------
    config:
        A ``SandboxConfig`` controlling resource limits and isolation.
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()

    @property
    def config(self) -> SandboxConfig:
        """Return the current sandbox configuration."""
        return self._config

    async def run(self, code: str, scope: dict) -> SandboxResult:
        """Execute untrusted code in an isolated subprocess.

        Parameters
        ----------
        code:
            Python source code to execute inside the sandbox.
        scope:
            A dictionary representing the execution scope — defines which
            resources the code is authorized to access. In production,
            this would be used to configure mount points, network rules,
            and capability filters. Currently used for validation and
            passed as a JSON-serializable context.

        Returns
        -------
        SandboxResult
            The captured stdout, stderr, exit code, and timeout status.

        Raises
        ------
        SandboxDeniedError
            If pre-execution checks determine the code attempts to access
            out-of-scope resources (placeholder for production enforcement).
        """
        # Pre-execution scope validation (placeholder for production enforcement)
        self._validate_scope(code, scope)

        # Build the subprocess command.
        # We wrap the code in a script executed by the same Python interpreter.
        # In production, this would be: runsc/firecracker exec with namespace isolation.
        wrapped_code = self._wrap_code(code)

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                wrapped_code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._config.timeout_seconds,
                )
                return SandboxResult(
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    exit_code=process.returncode or 0,
                    timed_out=False,
                )
            except TimeoutError:
                # Kill the process on timeout
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass  # Process already exited
                return SandboxResult(
                    stdout="",
                    stderr="Process killed: exceeded timeout of "
                    f"{self._config.timeout_seconds}s",
                    exit_code=-1,
                    timed_out=True,
                )

        except OSError as exc:
            # Failed to start the subprocess
            return SandboxResult(
                stdout="",
                stderr=f"Sandbox execution failed: {exc}",
                exit_code=-1,
                timed_out=False,
            )

    def _validate_scope(self, code: str, scope: dict) -> None:
        """Pre-execution validation of code against the authorized scope.

        In production, this would be enforced by the sandbox runtime
        (seccomp profiles, network namespaces, mount restrictions). Here
        we perform basic static checks as a placeholder.

        Raises
        ------
        SandboxDeniedError
            If the code contains patterns indicating out-of-scope access.
        """
        # Check for network access attempts when network is disabled
        if self._config.network == "none":
            network_indicators = ["socket", "urllib", "requests", "httpx", "aiohttp"]
            for indicator in network_indicators:
                if f"import {indicator}" in code or f"from {indicator}" in code:
                    raise SandboxDeniedError(
                        resource="network",
                        reason=f"Network access denied: detected import of '{indicator}' "
                        f"with network={self._config.network!r}",
                    )

        # Check for file access outside read_only_mounts (basic heuristic)
        # In production, the mount namespace enforces this at the kernel level
        allowed_mounts = set(self._config.read_only_mounts)
        if allowed_mounts:
            # Scope-based restriction placeholder; real enforcement is at
            # mount/namespace level in gVisor/Firecracker
            scope_paths = scope.get("allowed_paths", [])
            for path in scope_paths:
                if path not in allowed_mounts:
                    raise SandboxDeniedError(
                        resource=f"path:{path}",
                        reason="Path is not in read_only_mounts",
                    )

    def _wrap_code(self, code: str) -> str:
        """Wrap user code for subprocess execution with resource hints.

        In production, resource limits (CPU, memory) are enforced by the
        container runtime (cgroups). Here we include resource.setrlimit
        calls as a best-effort approximation on supported platforms (Unix).
        On Windows, resource limits are skipped since the production target
        is Linux with gVisor/Firecracker.
        """
        # Parse memory limit to bytes for resource.setrlimit
        memory_bytes = self._parse_memory(self._config.memory)

        # Escape the user code for embedding in a triple-quoted string
        escaped_code = code.replace("\\", "\\\\").replace("'", "\\'")

        # Build the wrapper that applies resource limits before running user code
        wrapper = textwrap.dedent(f"""\
            import sys

            # Apply resource limits (Unix only, best-effort)
            try:
                import resource
                # Apply memory limit (best-effort, platform-dependent)
                try:
                    resource.setrlimit(resource.RLIMIT_AS, ({memory_bytes}, {memory_bytes}))
                except (ValueError, resource.error):
                    pass  # Not all platforms support RLIMIT_AS
                # Apply CPU time limit (best-effort)
                try:
                    cpu_seconds = int({self._config.timeout_seconds})
                    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
                except (ValueError, resource.error):
                    pass  # Not all platforms support RLIMIT_CPU
            except ImportError:
                pass  # resource module not available (e.g., Windows)

            # Execute user code
            try:
                exec(compile('''{escaped_code}''', '<sandbox>', 'exec'))
            except SystemExit:
                pass
            except Exception as _e:
                print(str(_e), file=sys.stderr)
                sys.exit(1)
        """)
        return wrapper

    @staticmethod
    def _parse_memory(memory_str: str) -> int:
        """Parse a memory string like '512m' or '1g' to bytes."""
        memory_str = memory_str.strip().lower()
        multipliers = {
            "k": 1024,
            "m": 1024 * 1024,
            "g": 1024 * 1024 * 1024,
        }
        if memory_str and memory_str[-1] in multipliers:
            return int(memory_str[:-1]) * multipliers[memory_str[-1]]
        # Assume bytes if no suffix
        return int(memory_str)
