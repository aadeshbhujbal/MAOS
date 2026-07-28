"""Subagent roster definitions for MAOS v1.

This module provides factory functions that return the v1 subagent
specifications registered into the Agent_Registry at service startup.
Each SubagentSpec binds a role to a Platform_System, OperatingMode, skill
set, agentic capability budgets, and MCP allow-list.

Roster is extensible: additional SubagentSpecs can be added via the
Agent_Registry without changing orchestrator code (Req 13.1).

The specialized roster (``build_specialized_roster``) registers 16+ domain-
specific agents per Requirements 13.1-13.13, each with defined skills,
capability budgets, and operational boundaries (read-only vs read-write).
"""

from __future__ import annotations

from maos.contracts.agents import AgenticCapability, Skill, SubagentSpec
from maos.contracts.work_units import OperatingMode, PlatformSystem


def build_runtime_roster() -> list[SubagentSpec]:
    """Return the v1 RUNTIME-mode subagent specs for the Backend platform.

    Per design Decision 5, RUNTIME mode (Backend only, v1) includes:
    - Appointment_Assistant: manages live appointment operations
    - Billing_Assistant: manages live billing/invoice operations with
      sensitive-action gating on write operations (Req 11.7)

    Both are restricted to domain-API MCP tools approved for RUNTIME use
    under the least-privilege policy (Req 5.8).

    Requirements: 4.8, 5.8, 11.7
    """
    appointment_assistant = SubagentSpec(
        subagent_id="Appointment_Assistant-backend-runtime",
        role="Appointment_Assistant",
        platform_system=PlatformSystem.BACKEND,
        mode=OperatingMode.RUNTIME,
        skills=[
            Skill(
                skill_id="appointments.read",
                input_contract={
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string"},
                        "date_range": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "string", "format": "date"},
                                "end": {"type": "string", "format": "date"},
                            },
                        },
                    },
                    "required": ["patient_id"],
                },
                output_contract={
                    "type": "object",
                    "properties": {
                        "appointments": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["appointments"],
                },
                operation_scope=["read"],
            ),
            Skill(
                skill_id="appointments.create",
                input_contract={
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string"},
                        "provider_id": {"type": "string"},
                        "slot": {"type": "string", "format": "date-time"},
                        "reason": {"type": "string"},
                    },
                    "required": ["patient_id", "provider_id", "slot"],
                },
                output_contract={
                    "type": "object",
                    "properties": {
                        "appointment_id": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["appointment_id", "status"],
                },
                operation_scope=["write"],
            ),
            Skill(
                skill_id="appointments.reschedule",
                input_contract={
                    "type": "object",
                    "properties": {
                        "appointment_id": {"type": "string"},
                        "new_slot": {"type": "string", "format": "date-time"},
                    },
                    "required": ["appointment_id", "new_slot"],
                },
                output_contract={
                    "type": "object",
                    "properties": {
                        "appointment_id": {"type": "string"},
                        "status": {"type": "string"},
                        "previous_slot": {"type": "string", "format": "date-time"},
                    },
                    "required": ["appointment_id", "status"],
                },
                operation_scope=["write"],
            ),
        ],
        capability=AgenticCapability(
            max_reasoning_steps=15,
            max_tool_invocations=8,
        ),
        mcp_allow_list=[
            "domain-api.appointments.read",
            "domain-api.appointments.create",
            "domain-api.appointments.reschedule",
        ],
        status="available",
        selection_priority=0,
    )

    billing_assistant = SubagentSpec(
        subagent_id="Billing_Assistant-backend-runtime",
        role="Billing_Assistant",
        platform_system=PlatformSystem.BACKEND,
        mode=OperatingMode.RUNTIME,
        skills=[
            Skill(
                skill_id="billing.invoice.read",
                input_contract={
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string"},
                        "invoice_id": {"type": "string"},
                        "status_filter": {"type": "string"},
                    },
                    "required": ["patient_id"],
                },
                output_contract={
                    "type": "object",
                    "properties": {
                        "invoices": {"type": "array", "items": {"type": "object"}},
                    },
                    "required": ["invoices"],
                },
                operation_scope=["read"],
            ),
            Skill(
                skill_id="billing.invoice.create",
                input_contract={
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string"},
                        "line_items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "amount": {"type": "number"},
                                    "code": {"type": "string"},
                                },
                                "required": ["description", "amount"],
                            },
                        },
                    },
                    "required": ["patient_id", "line_items"],
                },
                output_contract={
                    "type": "object",
                    "properties": {
                        "invoice_id": {"type": "string"},
                        "status": {"type": "string"},
                        "total": {"type": "number"},
                    },
                    "required": ["invoice_id", "status", "total"],
                },
                # Billing writes are sensitive — requires Human_Approval (Req 11.7)
                operation_scope=["write", "sensitive"],
            ),
        ],
        capability=AgenticCapability(
            max_reasoning_steps=15,
            max_tool_invocations=8,
        ),
        mcp_allow_list=[
            "domain-api.billing.read",
            "domain-api.billing.create",
        ],
        status="available",
        selection_priority=0,
    )

    return [appointment_assistant, billing_assistant]


def build_development_roster() -> list[SubagentSpec]:
    """Return the v1 DEVELOPMENT-mode subagent specs for Backend, Web, and Mobile.

    Per design Decision 5, each PlatformSystem (Backend/Web/Mobile) gets four
    DEVELOPMENT-mode subagents:

    1. Code_Reviewer — code review capability
    2. Debugger — debugging capability
    3. Security_Subagent — security analysis capability
    4. Feature_Implementer — feature implementation capability

    All specs use mode=DEVELOPMENT, status="available", selection_priority=0.
    IDs follow the pattern ``{role}-{platform}-dev``.

    Requirements: 4.8, 5.1, 13.1
    """
    roster: list[SubagentSpec] = []

    for platform in PlatformSystem:
        platform_tag = platform.value.lower()

        # 1. Code_Reviewer
        roster.append(
            SubagentSpec(
                subagent_id=f"code-reviewer-{platform_tag}-dev",
                role="Code_Reviewer",
                platform_system=platform,
                mode=OperatingMode.DEVELOPMENT,
                skills=[
                    Skill(
                        skill_id="code_review",
                        input_contract={},
                        output_contract={},
                        operation_scope=["filesystem.read", "git.read"],
                    )
                ],
                capability=AgenticCapability(
                    max_reasoning_steps=20,
                    max_tool_invocations=10,
                ),
                mcp_allow_list=["filesystem.read", "git.read"],
                status="available",
                selection_priority=0,
            )
        )

        # 2. Debugger
        roster.append(
            SubagentSpec(
                subagent_id=f"debugger-{platform_tag}-dev",
                role="Debugger",
                platform_system=platform,
                mode=OperatingMode.DEVELOPMENT,
                skills=[
                    Skill(
                        skill_id="debug",
                        input_contract={},
                        output_contract={},
                        operation_scope=[
                            "filesystem.read",
                            "git.read",
                            "code-exec.run",
                        ],
                    )
                ],
                capability=AgenticCapability(
                    max_reasoning_steps=30,
                    max_tool_invocations=15,
                ),
                mcp_allow_list=["filesystem.read", "git.read", "code-exec.run"],
                status="available",
                selection_priority=0,
            )
        )

        # 3. Security_Subagent
        roster.append(
            SubagentSpec(
                subagent_id=f"security-subagent-{platform_tag}-dev",
                role="Security_Subagent",
                platform_system=platform,
                mode=OperatingMode.DEVELOPMENT,
                skills=[
                    Skill(
                        skill_id="security_analysis",
                        input_contract={},
                        output_contract={},
                        operation_scope=[
                            "filesystem.read",
                            "git.read",
                            "sast.scan",
                        ],
                    )
                ],
                capability=AgenticCapability(
                    max_reasoning_steps=25,
                    max_tool_invocations=10,
                ),
                mcp_allow_list=["filesystem.read", "git.read", "sast.scan"],
                status="available",
                selection_priority=0,
            )
        )

        # 4. Feature_Implementer
        roster.append(
            SubagentSpec(
                subagent_id=f"feature-implementer-{platform_tag}-dev",
                role="Feature_Implementer",
                platform_system=platform,
                mode=OperatingMode.DEVELOPMENT,
                skills=[
                    Skill(
                        skill_id="implement_feature",
                        input_contract={},
                        output_contract={},
                        operation_scope=[
                            "filesystem.read",
                            "filesystem.write",
                            "git.read",
                            "git.branch",
                            "code-exec.run",
                        ],
                    )
                ],
                capability=AgenticCapability(
                    max_reasoning_steps=50,
                    max_tool_invocations=30,
                ),
                mcp_allow_list=[
                    "filesystem.read",
                    "filesystem.write",
                    "git.read",
                    "git.branch",
                    "code-exec.run",
                ],
                status="available",
                selection_priority=0,
            )
        )

    return roster


def build_specialized_roster() -> list[SubagentSpec]:
    """Return the 16 specialized agent specs for the AI Engineering Platform.

    Each agent is defined with:
    - Specific skills relevant to its domain
    - MCP allow-list restricting which tools it can invoke
    - Operational boundaries (read-only vs read-write per tool)
    - Capability budgets bounding reasoning and tool invocations
    - Knowledge tools (knowledge_search, graph_query, code_search) where appropriate

    Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9,
                  13.10, 13.11, 13.12, 13.13
    """
    roster: list[SubagentSpec] = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Backend_Agent — core backend service development (Req 13.1)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="backend-agent-dev",
            role="Backend_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="backend.implement",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="backend.api_design",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "filesystem.read",
                "filesystem.write",
                "git.read",
                "git.write",
                "Terminal_MCP",
                "GitHub_MCP",
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Frontend_Agent — web frontend development (Req 13.1)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="frontend-agent-dev",
            role="Frontend_Agent",
            platform_system=PlatformSystem.WEB,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="frontend.implement",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="frontend.component_design",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "filesystem.read",
                "filesystem.write",
                "git.read",
                "git.write",
                "Terminal_MCP",
                "GitHub_MCP",
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Security_Agent — security analysis, vulnerability scanning (Req 13.1)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="security-agent-dev",
            role="Security_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="security.scan",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="security.audit",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="security.fix",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=40,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "filesystem.read",
                "git.read",
                "Terminal_MCP",
                "GitHub_MCP",
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. DevOps_Agent — Docker, K8s, CI/CD, pipelines (Req 13.3)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="devops-agent-dev",
            role="DevOps_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="devops.container_management",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="devops.orchestration",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="devops.ci_cd",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=40,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "Docker_MCP",
                "Kubernetes_MCP",
                "Terminal_MCP",
                "GitHub_MCP",
                "knowledge_search",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. QA_Agent — test generation, browser testing, PR reporting (Req 13.4)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="qa-agent-dev",
            role="QA_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="qa.test_generation",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="qa.browser_testing",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="qa.test_execution",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=40,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "Terminal_MCP",
                "Playwright_MCP",
                "GitHub_MCP",
                "knowledge_search",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Documentation_Agent — docs, wikis, ADRs, changelogs (Req 13.5)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="documentation-agent-dev",
            role="Documentation_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="docs.generate",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="docs.update_wiki",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="docs.adr",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=30,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "Confluence_MCP",
                "GitHub_MCP",
                "Filesystem_MCP",
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Architecture_Agent — design review, scalability, patterns (Req 13.6)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="architecture-agent-dev",
            role="Architecture_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="architecture.design_review",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="architecture.scalability_analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="architecture.impact_analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "knowledge_search",
                "graph_query",
                "GitHub_MCP",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Database_Agent — SQL, indexes, migrations, schema (Req 13.7)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="database-agent-dev",
            role="Database_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="database.query_optimization",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="database.migration",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="database.schema_evolution",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="database.index_recommendation",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=35,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "Database_MCP",
                "Terminal_MCP",
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Monitoring_Agent — dashboards, metrics, logs, alerts (Req 13.8)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="monitoring-agent-dev",
            role="Monitoring_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="monitoring.dashboard_query",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="monitoring.metric_analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="monitoring.log_analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="monitoring.alert_management",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=30,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "Grafana_MCP",
                "Prometheus_MCP",
                "Loki_MCP",
                "Sentry_MCP",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Incident_Response_Agent — alert detection, RCA, fixes (Req 13.9)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="incident-response-agent-dev",
            role="Incident_Response_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="incident.detect",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="incident.log_analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="incident.root_cause_analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="incident.remediation",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="incident.notification",
                    input_contract={},
                    output_contract={},
                    operation_scope=["write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "Grafana_MCP",
                "Loki_MCP",
                "Prometheus_MCP",
                "Sentry_MCP",
                "Slack_MCP",
                "Kubernetes_MCP",
                "knowledge_search",
                "graph_query",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Infrastructure_Agent — cloud provisioning, networking (Req 13.10)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="infrastructure-agent-dev",
            role="Infrastructure_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="infra.provision",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="infra.networking",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="infra.load_balancing",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="infra.resource_management",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=40,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "AWS_MCP",
                "Azure_MCP",
                "GCP_MCP",
                "Terminal_MCP",
                "knowledge_search",
                "graph_query",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 12. ML_AI_Agent — model training, evaluation, deployment (Req 13.11)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="ml-ai-agent-dev",
            role="ML_AI_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="ml.train",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="ml.evaluate",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="ml.deploy",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="ml.pipeline",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "Terminal_MCP",
                "GCP_MCP",
                "AWS_MCP",
                "knowledge_search",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 13. UI_UX_Agent — design systems, accessibility, responsive (Req 13.12)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="ui-ux-agent-dev",
            role="UI_UX_Agent",
            platform_system=PlatformSystem.WEB,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="uiux.design_extraction",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="uiux.accessibility_audit",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="uiux.responsive_validation",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="uiux.component_spec",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=35,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "Figma_MCP",
                "Chrome_MCP",
                "Playwright_MCP",
                "knowledge_search",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 14. API_Agent — OpenAPI, versioning, rate limiting (Req 13.13)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="api-agent-dev",
            role="API_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="api.openapi_generation",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="api.versioning",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="api.rate_limiting",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=35,
                max_tool_invocations=20,
            ),
            mcp_allow_list=[
                "Terminal_MCP",
                "GitHub_MCP",
                "Database_MCP",
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 15. Mobile_Agent — mobile app development (Req 13.1)
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="mobile-agent-dev",
            role="Mobile_Agent",
            platform_system=PlatformSystem.MOBILE,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="mobile.implement",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="mobile.ui_design",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="mobile.testing",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "filesystem.read",
                "filesystem.write",
                "git.read",
                "git.write",
                "Terminal_MCP",
                "GitHub_MCP",
                "knowledge_search",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 16. Planning_Agent — NL decomposition, LLM-only (Req 13.1)
    #     No MCP tools — uses LLM reasoning only for task planning.
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="planning-agent-dev",
            role="Planning_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="planning.decompose",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="planning.assign_agents",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="planning.estimate_effort",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=60,
                max_tool_invocations=5,
            ),
            mcp_allow_list=[
                "knowledge_search",
                "graph_query",
            ],
            status="available",
            selection_priority=0,
        )
    )

    return roster


def build_full_platform_roster() -> list[SubagentSpec]:
    """Return the full 16-agent platform roster for the AI Engineering Platform.

    Each agent is configured with:
    - Domain-specific skills matching its specialization
    - MCP allow-list controlling tool access
    - AgenticCapability bounds (30-100 reasoning steps, 10-50 tool invocations)
    - Operational boundaries (read-only vs read-write)

    This function provides the canonical roster used by the platform deployment,
    with agents matching the exact skill/MCP specifications from the platform
    design document.

    Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9,
                  13.10, 13.11, 13.12, 13.13
    """
    roster: list[SubagentSpec] = []

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Backend_Agent — core backend development (Req 13.1)
    #    Skills: implement-feature, debug-runtime, review-code
    #    MCP: filesystem, git, terminal, database, knowledge_search, graph_query
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-backend-agent",
            role="Backend_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="implement-feature",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="debug-runtime",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="review-code",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=100,
                max_tool_invocations=50,
            ),
            mcp_allow_list=[
                "filesystem",
                "git",
                "terminal",
                "database",
                "knowledge_search",
                "graph_query",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Frontend_Agent — web frontend development (Req 13.1)
    #    Skills: implement-ui, review-code
    #    MCP: filesystem, git, chrome, playwright, figma, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-frontend-agent",
            role="Frontend_Agent",
            platform_system=PlatformSystem.WEB,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="implement-ui",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="review-code",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=80,
                max_tool_invocations=40,
            ),
            mcp_allow_list=[
                "filesystem",
                "git",
                "chrome",
                "playwright",
                "figma",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Mobile_Agent — mobile app development (Req 13.1)
    #    Skills: implement-mobile, debug-mobile
    #    MCP: filesystem, git, terminal, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-mobile-agent",
            role="Mobile_Agent",
            platform_system=PlatformSystem.MOBILE,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="implement-mobile",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="debug-mobile",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=80,
                max_tool_invocations=40,
            ),
            mcp_allow_list=[
                "filesystem",
                "git",
                "terminal",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Security_Agent — security auditing and vuln scanning (Req 13.1)
    #    Skills: security-audit, vuln-scan
    #    MCP: filesystem, git, terminal, knowledge_search, graph_query
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-security-agent",
            role="Security_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="security-audit",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="vuln-scan",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=60,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "filesystem",
                "git",
                "terminal",
                "knowledge_search",
                "graph_query",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. DevOps_Agent — CI/CD, containers, orchestration (Req 13.3)
    #    Skills: deploy, ci-cd, infrastructure
    #    MCP: docker, kubernetes, terminal, github, aws, azure, gcp,
    #         knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-devops-agent",
            role="DevOps_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="deploy",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="ci-cd",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="infrastructure",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=60,
                max_tool_invocations=35,
            ),
            mcp_allow_list=[
                "docker",
                "kubernetes",
                "terminal",
                "github",
                "aws",
                "azure",
                "gcp",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. QA_Agent — testing and quality assurance (Req 13.4)
    #    Skills: write-tests, run-tests, load-test
    #    MCP: terminal, playwright, chrome, github, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-qa-agent",
            role="QA_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="write-tests",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="run-tests",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="load-test",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=60,
                max_tool_invocations=35,
            ),
            mcp_allow_list=[
                "terminal",
                "playwright",
                "chrome",
                "github",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Documentation_Agent — docs and API documentation (Req 13.5)
    #    Skills: write-docs, generate-api-docs
    #    MCP: filesystem, github, confluence, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-documentation-agent",
            role="Documentation_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="write-docs",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="generate-api-docs",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=40,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "filesystem",
                "github",
                "confluence",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Architecture_Agent — design review and scalability (Req 13.6)
    #    Skills: design-review, scalability-analysis
    #    MCP: knowledge_search, graph_query, code_search, github
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-architecture-agent",
            role="Architecture_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="design-review",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="scalability-analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=80,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "knowledge_search",
                "graph_query",
                "code_search",
                "github",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Database_Agent — SQL, schemas, migrations (Req 13.7)
    #    Skills: sql-optimize, schema-design, migration
    #    MCP: database, terminal, knowledge_search, graph_query
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-database-agent",
            role="Database_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="sql-optimize",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="schema-design",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="migration",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "database",
                "terminal",
                "knowledge_search",
                "graph_query",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Monitoring_Agent — metrics and log analysis (Req 13.8)
    #     Skills: metric-analysis, log-analysis
    #     MCP: grafana, prometheus, loki, sentry, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-monitoring-agent",
            role="Monitoring_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="metric-analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="log-analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=40,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "grafana",
                "prometheus",
                "loki",
                "sentry",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Incident_Response_Agent — RCA and incident triage (Req 13.9)
    #     Skills: root-cause-analysis, incident-triage
    #     MCP: grafana, loki, prometheus, sentry, slack, kubernetes,
    #          knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-incident-response-agent",
            role="Incident_Response_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="root-cause-analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="incident-triage",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=80,
                max_tool_invocations=40,
            ),
            mcp_allow_list=[
                "grafana",
                "loki",
                "prometheus",
                "sentry",
                "slack",
                "kubernetes",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 12. Infrastructure_Agent — cloud provisioning (Req 13.10)
    #     Skills: cloud-provision, networking
    #     MCP: aws, azure, gcp, terminal, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-infrastructure-agent",
            role="Infrastructure_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="cloud-provision",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="networking",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "aws",
                "azure",
                "gcp",
                "terminal",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 13. ML_AI_Agent — model training and ML pipelines (Req 13.11)
    #     Skills: model-training, ml-pipeline
    #     MCP: terminal, gcp, aws, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-ml-ai-agent",
            role="ML_AI_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="model-training",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="ml-pipeline",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=60,
                max_tool_invocations=30,
            ),
            mcp_allow_list=[
                "terminal",
                "gcp",
                "aws",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 14. UI_UX_Agent — design review and accessibility (Req 13.12)
    #     Skills: design-review, accessibility-audit
    #     MCP: figma, chrome, playwright, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-ui-ux-agent",
            role="UI_UX_Agent",
            platform_system=PlatformSystem.WEB,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="design-review",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="accessibility-audit",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "figma",
                "chrome",
                "playwright",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 15. API_Agent — API design and OpenAPI specs (Req 13.13)
    #     Skills: api-design, openapi-spec
    #     MCP: terminal, github, database, knowledge_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-api-agent",
            role="API_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="api-design",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
                Skill(
                    skill_id="openapi-spec",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read", "write"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=50,
                max_tool_invocations=25,
            ),
            mcp_allow_list=[
                "terminal",
                "github",
                "database",
                "knowledge_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    # ─────────────────────────────────────────────────────────────────────────
    # 16. Planning_Agent — task decomposition and planning (Req 13.1)
    #     Skills: task-decomposition, impact-analysis
    #     MCP: knowledge_search, graph_query, code_search
    # ─────────────────────────────────────────────────────────────────────────
    roster.append(
        SubagentSpec(
            subagent_id="platform-planning-agent",
            role="Planning_Agent",
            platform_system=PlatformSystem.BACKEND,
            mode=OperatingMode.DEVELOPMENT,
            skills=[
                Skill(
                    skill_id="task-decomposition",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
                Skill(
                    skill_id="impact-analysis",
                    input_contract={},
                    output_contract={},
                    operation_scope=["read"],
                ),
            ],
            capability=AgenticCapability(
                max_reasoning_steps=100,
                max_tool_invocations=10,
            ),
            mcp_allow_list=[
                "knowledge_search",
                "graph_query",
                "code_search",
            ],
            status="available",
            selection_priority=0,
        )
    )

    return roster
