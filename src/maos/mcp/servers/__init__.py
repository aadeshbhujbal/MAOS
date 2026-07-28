"""MCP Server Stubs Package

This package contains stub implementations for 16 MCP servers as defined in
the KB-10u specification. These are server-side stubs that provide the
tool signatures and placeholder responses.

Each server extends ``MCPServerBase`` and defines:
- ``name``: unique server identifier
- ``access_tier``: ``read``, ``read_write``, or ``admin``
- ``auth_method``: ``oauth2``, ``api_key``, ``mTLS``, or ``none``
- ``supported_tools``: list of tool name strings

Available Servers:
- ``file_system``: File system operations (read_write)
- ``code_analysis``: Code analysis and AST parsing (read)
- ``git_operations``: Git repository operations (read_write)
- ``testing``: Test discovery and execution (read_write)
- ``docker``: Docker container management (admin)
- ``database``: Database query execution (read_write)
- ``environment``: Environment variable access (read)
- ``llm_provider``: LLM model inference (read_write)
- ``cicd``: CI/CD pipeline operations (admin)
- ``cost_management``: Cost tracking and budgeting (read_write)
- ``knowledge_base``: Document upload and search (read_write)
- ``cloud_services``: Cloud infrastructure operations (admin)
- ``security_scanner``: Static and dynamic security scanning (read)
- ``observability``: Metrics, traces, and logs retrieval (read)
- ``api_integration``: API testing and contract management (read_write)
- ``notification``: Multi-channel notification delivery (read_write)
- ``secret_manager``: Secret retrieval and rotation (admin)
- ``agent_management``: Agent lifecycle management (admin)
- ``task_flow``: Task/subtask lifecycle management (read_write)
- ``access_control``: RBAC policy enforcement (admin)

Requirements: KB-10u 17.1, 17.2, 17.3.
"""

from .access_control import AccessControlMCPServer
from .agent_management import AgentManagementMCPServer
from .api_integration import APIIntegrationMCPServer
from .base import MCPServerBase, ServerConfig
from .cicd import CICDMCPServer
from .cloud_services import CloudServicesMCPServer
from .code_analysis import CodeAnalysisMCPServer
from .cost_management import CostManagementMCPServer
from .database import DatabaseMCPServer
from .docker import DockerMCPServer
from .environment import EnvironmentMCPServer
from .file_system import FileSystemMCPServer
from .git_operations import GitOperationsMCPServer
from .knowledge_base import KnowledgeBaseMCPServer
from .llm_provider import LLMProviderMCPServer
from .notification import NotificationMCPServer
from .observability import ObservabilityMCPServer
from .secret_manager import SecretManagerMCPServer
from .security_scanner import SecurityScannerMCPServer
from .task_flow import TaskFlowMCPServer
from .testing import TestingMCPServer

__all__ = [
    "APIIntegrationMCPServer",
    "AccessControlMCPServer",
    "AgentManagementMCPServer",
    "CICDMCPServer",
    "CloudServicesMCPServer",
    "CodeAnalysisMCPServer",
    "CostManagementMCPServer",
    "DatabaseMCPServer",
    "DockerMCPServer",
    "EnvironmentMCPServer",
    "FileSystemMCPServer",
    "GitOperationsMCPServer",
    "KnowledgeBaseMCPServer",
    "LLMProviderMCPServer",
    "MCPServerBase",
    "NotificationMCPServer",
    "ObservabilityMCPServer",
    "SecretManagerMCPServer",
    "SecurityScannerMCPServer",
    "ServerConfig",
    "TaskFlowMCPServer",
    "TestingMCPServer",
]
