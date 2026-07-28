"""Quick smoke test for MCPRegistry imports."""
import sys
sys.path.insert(0, "src")

from maos.mcp.registry import (
    DuplicateServerError,
    MCPRegistry,
    ToolNotAllowedError,
    ToolNotFoundError,
)
from maos.mcp.models import MCPServerRecord, MCPToolResolution

# Verify class instantiation
registry = MCPRegistry()
assert hasattr(registry, "register")
assert hasattr(registry, "deregister")
assert hasattr(registry, "resolve_tool")
assert hasattr(registry, "list_servers")
assert hasattr(registry, "get_server")
assert hasattr(registry, "update_health")
assert hasattr(registry, "rotate_credentials")

print("All imports and basic checks passed!")
