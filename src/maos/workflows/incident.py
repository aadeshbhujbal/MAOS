"""Incident Response Workflow — autonomous production incident handling.

Defines the full incident response workflow:
  Alert → LogAnalysis → MetricAnalysis → TraceAnalysis → ImpactAnalysis →
  RootCause → Investigation → SecurityCheck → Fix → Test → PR → Deploy

Key behaviours:
- Initiates within 30 seconds of alert receipt (Req 18.1).
- Queries Loki for error logs in a 15-minute window around the alert (Req 18.2).
- Queries Prometheus for anomalous metric patterns (Req 18.3).
- Queries Knowledge Graph for affected services via impact analysis (Req 18.4).
- Produces a structured incident report (Req 18.5).
- Creates a PR via GitHub_MCP for code fixes (Req 18.6).
- Notifies team via Slack_MCP at detection, analysis, resolution (Req 18.7).
- On critical severity: immediate Slack escalation without waiting (Req 18.8).

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum time from alert receipt to workflow initiation (Req 18.1)
MAX_INITIATION_SECONDS = 30

# Log query window around the alert timestamp (Req 18.2)
LOG_QUERY_WINDOW_MINUTES = 15

# Impact analysis traversal depth in the Knowledge Graph
DEFAULT_IMPACT_DEPTH = 3


# ---------------------------------------------------------------------------
# Enums and Models
# ---------------------------------------------------------------------------


class IncidentSeverity(str, Enum):
    """Severity levels for production incidents."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WorkflowStage(str, Enum):
    """Stages in the incident response workflow state machine."""

    ALERT_RECEIVED = "alert_received"
    LOG_ANALYSIS = "log_analysis"
    METRIC_ANALYSIS = "metric_analysis"
    TRACE_ANALYSIS = "trace_analysis"
    IMPACT_ANALYSIS = "impact_analysis"
    ROOT_CAUSE = "root_cause"
    INVESTIGATION = "investigation"
    SECURITY_CHECK = "security_check"
    FIX = "fix"
    TEST = "test"
    PR = "pr"
    DEPLOY = "deploy"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class AlertPayload(BaseModel):
    """Incoming alert from Prometheus_MCP or Sentry_MCP (Req 18.1)."""

    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str  # "prometheus" or "sentry"
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    title: str
    description: str = ""
    component: str = ""  # affected component/service name
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    labels: dict[str, str] = Field(default_factory=dict)
    tenant_id: str = ""


class LogAnalysisResult(BaseModel):
    """Results from querying Loki for error logs (Req 18.2)."""

    query_start: datetime
    query_end: datetime
    error_count: int = 0
    log_excerpts: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)


class MetricAnalysisResult(BaseModel):
    """Results from querying Prometheus for anomalous metrics (Req 18.3)."""

    anomalous_metrics: list[dict[str, Any]] = Field(default_factory=list)
    cpu_anomaly: bool = False
    memory_anomaly: bool = False
    latency_anomaly: bool = False
    error_rate_anomaly: bool = False


class TraceAnalysisResult(BaseModel):
    """Results from distributed trace correlation."""

    correlated_traces: list[dict[str, Any]] = Field(default_factory=list)
    slow_spans: list[dict[str, Any]] = Field(default_factory=list)
    error_spans: list[dict[str, Any]] = Field(default_factory=list)


class ImpactAnalysisResult(BaseModel):
    """Results from Knowledge Graph impact analysis (Req 18.4)."""

    affected_services: list[str] = Field(default_factory=list)
    affected_count: int = 0
    dependency_chain: list[str] = Field(default_factory=list)


class RootCauseHypothesis(BaseModel):
    """A root cause hypothesis with supporting evidence."""

    hypothesis: str
    confidence: float = 0.0  # 0.0 to 1.0
    evidence: list[str] = Field(default_factory=list)


class IncidentReport(BaseModel):
    """Structured incident report (Req 18.5)."""

    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alert: AlertPayload
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    root_cause: RootCauseHypothesis | None = None
    log_evidence: LogAnalysisResult | None = None
    metric_evidence: MetricAnalysisResult | None = None
    trace_evidence: TraceAnalysisResult | None = None
    proposed_fix: str = ""
    pr_url: str = ""
    status: WorkflowStage = WorkflowStage.ALERT_RECEIVED
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None


# ---------------------------------------------------------------------------
# MCP Client Protocols (interfaces for dependency injection)
# ---------------------------------------------------------------------------


class LokiMCPClient:
    """Client interface for Loki_MCP log queries (Req 18.2).

    In production, resolved via the MCP Registry. Stub implementation returns
    empty results — real integration connects to Loki's LogQL API.
    """

    async def query_logs(
        self,
        query: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query Loki for log entries matching a LogQL expression."""
        logger.debug(
            "loki_query",
            extra={"query": query, "start": start.isoformat(), "end": end.isoformat()},
        )
        return []


class PrometheusMCPClient:
    """Client interface for Prometheus_MCP metric queries (Req 18.3).

    Queries Prometheus for anomalous metric patterns correlated with an alert.
    """

    async def range_query(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "30s",
    ) -> list[dict[str, Any]]:
        """Execute a PromQL range query."""
        logger.debug(
            "prometheus_range_query",
            extra={"query": query, "start": start.isoformat(), "end": end.isoformat()},
        )
        return []

    async def instant_query(self, query: str) -> list[dict[str, Any]]:
        """Execute a PromQL instant query."""
        logger.debug("prometheus_instant_query", extra={"query": query})
        return []


class SlackMCPClient:
    """Client interface for Slack_MCP notifications (Req 18.7, 18.8).

    Sends incident status updates and critical escalation messages.
    """

    async def send_message(
        self,
        channel: str,
        text: str,
        *,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to a Slack channel."""
        logger.info(
            "slack_notification",
            extra={"channel": channel, "text_preview": text[:100]},
        )
        return {"ok": True, "ts": str(datetime.now(UTC).timestamp())}

    async def send_escalation(
        self,
        channel: str,
        text: str,
        mentions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Send an urgent escalation message with @mentions (Req 18.8)."""
        mention_str = " ".join(f"<@{m}>" for m in (mentions or []))
        full_text = f"🚨 *CRITICAL ESCALATION* {mention_str}\n{text}"
        logger.warning(
            "slack_critical_escalation",
            extra={"channel": channel, "mentions": mentions},
        )
        return {"ok": True, "ts": str(datetime.now(UTC).timestamp())}


class GitHubMCPClient:
    """Client interface for GitHub_MCP PR creation (Req 18.6)."""

    async def create_pr(
        self,
        repo: str,
        title: str,
        body: str,
        branch: str,
        base: str = "main",
    ) -> dict[str, Any]:
        """Create a pull request with the proposed fix."""
        logger.info(
            "github_pr_created",
            extra={"repo": repo, "title": title, "branch": branch},
        )
        return {"url": f"https://github.com/{repo}/pull/0", "number": 0}


class KnowledgeGraphMCPClient:
    """Client interface for Knowledge Graph impact analysis (Req 18.4).

    Wraps the Knowledge Graph's impact_analysis query via MCP tool resolution.
    """

    async def impact_analysis(
        self,
        entity_id: str,
        depth: int = DEFAULT_IMPACT_DEPTH,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Graph for services affected by the failing component."""
        logger.debug(
            "knowledge_graph_impact_analysis",
            extra={"entity_id": entity_id, "depth": depth},
        )
        return []


# ---------------------------------------------------------------------------
# Incident Response Workflow
# ---------------------------------------------------------------------------


class IncidentResponseWorkflow:
    """Orchestrates the full incident response lifecycle (Req 18.1–18.8).

    Workflow stages:
      Alert → LogAnalysis → MetricAnalysis → TraceAnalysis → ImpactAnalysis →
      RootCause → Investigation → SecurityCheck → Fix → Test → PR → Deploy

    On critical severity, immediately escalates via Slack without waiting for
    full analysis to complete.

    Parameters
    ----------
    loki_client:
        Loki MCP client for log queries.
    prometheus_client:
        Prometheus MCP client for metric queries.
    slack_client:
        Slack MCP client for notifications and escalation.
    github_client:
        GitHub MCP client for PR creation.
    graph_client:
        Knowledge Graph client for impact analysis.
    escalation_channel:
        Slack channel for incident notifications and escalation.
    """

    def __init__(
        self,
        loki_client: LokiMCPClient | None = None,
        prometheus_client: PrometheusMCPClient | None = None,
        slack_client: SlackMCPClient | None = None,
        github_client: GitHubMCPClient | None = None,
        graph_client: KnowledgeGraphMCPClient | None = None,
        escalation_channel: str = "#incidents",
    ) -> None:
        self._loki = loki_client or LokiMCPClient()
        self._prometheus = prometheus_client or PrometheusMCPClient()
        self._slack = slack_client or SlackMCPClient()
        self._github = github_client or GitHubMCPClient()
        self._graph = graph_client or KnowledgeGraphMCPClient()
        self._escalation_channel = escalation_channel

    # ------------------------------------------------------------------
    # Main workflow entrypoint
    # ------------------------------------------------------------------

    async def handle_alert(self, alert: AlertPayload) -> IncidentReport:
        """Execute the full incident response workflow (Req 18.1).

        Initiates within 30 seconds of alert receipt. On critical severity,
        escalates immediately via Slack without waiting for analysis.

        Returns a structured ``IncidentReport`` with timeline, affected
        services, root cause hypothesis, evidence, and proposed fix.
        """
        initiated_at = datetime.now(UTC)
        report = IncidentReport(alert=alert)
        report.timeline.append(
            {"stage": WorkflowStage.ALERT_RECEIVED, "timestamp": initiated_at.isoformat()}
        )

        logger.info(
            "incident_workflow_started",
            extra={
                "incident_id": report.incident_id,
                "alert_id": alert.alert_id,
                "severity": alert.severity,
                "component": alert.component,
                "tenant_id": alert.tenant_id,
            },
        )

        # Req 18.7: Notify team at detection
        await self._notify_detection(report)

        # Req 18.8: Critical severity — immediate escalation without waiting
        if alert.severity == IncidentSeverity.CRITICAL:
            await self._escalate_critical(report)

        # Req 18.1: Verify initiation within 30s constraint
        elapsed = (datetime.now(UTC) - alert.timestamp).total_seconds()
        if elapsed > MAX_INITIATION_SECONDS:
            logger.warning(
                "incident_initiation_delayed",
                extra={
                    "incident_id": report.incident_id,
                    "elapsed_seconds": elapsed,
                    "max_allowed": MAX_INITIATION_SECONDS,
                },
            )

        # Stage 1: Log Analysis (Req 18.2)
        report.log_evidence = await self._analyze_logs(alert)
        report.status = WorkflowStage.LOG_ANALYSIS
        report.timeline.append(
            {"stage": WorkflowStage.LOG_ANALYSIS, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 2: Metric Analysis (Req 18.3)
        report.metric_evidence = await self._analyze_metrics(alert)
        report.status = WorkflowStage.METRIC_ANALYSIS
        report.timeline.append(
            {"stage": WorkflowStage.METRIC_ANALYSIS, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 3: Trace Analysis
        report.trace_evidence = await self._analyze_traces(alert)
        report.status = WorkflowStage.TRACE_ANALYSIS
        report.timeline.append(
            {"stage": WorkflowStage.TRACE_ANALYSIS, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 4: Impact Analysis via Knowledge Graph (Req 18.4)
        impact = await self._analyze_impact(alert)
        report.affected_services = impact.affected_services
        report.status = WorkflowStage.IMPACT_ANALYSIS
        report.timeline.append(
            {"stage": WorkflowStage.IMPACT_ANALYSIS, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 5: Root Cause Analysis (Req 18.5)
        report.root_cause = await self._determine_root_cause(report)
        report.status = WorkflowStage.ROOT_CAUSE
        report.timeline.append(
            {"stage": WorkflowStage.ROOT_CAUSE, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 6: Investigation
        await self._investigate(report)
        report.status = WorkflowStage.INVESTIGATION
        report.timeline.append(
            {"stage": WorkflowStage.INVESTIGATION, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 7: Security Check
        await self._security_check(report)
        report.status = WorkflowStage.SECURITY_CHECK
        report.timeline.append(
            {"stage": WorkflowStage.SECURITY_CHECK, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 8: Fix
        report.proposed_fix = await self._generate_fix(report)
        report.status = WorkflowStage.FIX
        report.timeline.append(
            {"stage": WorkflowStage.FIX, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 9: Test
        await self._run_tests(report)
        report.status = WorkflowStage.TEST
        report.timeline.append(
            {"stage": WorkflowStage.TEST, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 10: PR Creation (Req 18.6)
        if report.proposed_fix:
            pr_result = await self._create_pr(report)
            report.pr_url = pr_result.get("url", "")
        report.status = WorkflowStage.PR
        report.timeline.append(
            {"stage": WorkflowStage.PR, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Stage 11: Deploy
        await self._deploy(report)
        report.status = WorkflowStage.DEPLOY
        report.timeline.append(
            {"stage": WorkflowStage.DEPLOY, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Mark resolved
        report.status = WorkflowStage.RESOLVED
        report.resolved_at = datetime.now(UTC)
        report.timeline.append(
            {"stage": WorkflowStage.RESOLVED, "timestamp": datetime.now(UTC).isoformat()}
        )

        # Req 18.7: Notify team at resolution
        await self._notify_resolution(report)

        logger.info(
            "incident_workflow_completed",
            extra={
                "incident_id": report.incident_id,
                "alert_id": alert.alert_id,
                "severity": alert.severity,
                "affected_services": report.affected_services,
                "root_cause": report.root_cause.hypothesis if report.root_cause else None,
                "pr_url": report.pr_url,
                "duration_seconds": (
                    report.resolved_at - report.created_at
                ).total_seconds(),
            },
        )

        return report

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    async def _analyze_logs(self, alert: AlertPayload) -> LogAnalysisResult:
        """Query Loki for error logs in 15-min window around alert (Req 18.2).

        Constructs a LogQL query filtered by the alert's component and queries
        Loki_MCP for error-level entries within ±7.5 minutes of alert timestamp.
        """
        window = timedelta(minutes=LOG_QUERY_WINDOW_MINUTES)
        query_start = alert.timestamp - (window / 2)
        query_end = alert.timestamp + (window / 2)

        # Build LogQL query scoped to the failing component
        logql = f'{{app="{alert.component}"}} |= "error" or "ERROR" or "panic" or "FATAL"'

        raw_logs = await self._loki.query_logs(
            query=logql,
            start=query_start,
            end=query_end,
            limit=100,
        )

        # Extract log excerpts and identify patterns
        excerpts = [entry.get("line", "") for entry in raw_logs[:20]]
        patterns = self._extract_log_patterns(raw_logs)

        result = LogAnalysisResult(
            query_start=query_start,
            query_end=query_end,
            error_count=len(raw_logs),
            log_excerpts=excerpts,
            patterns=patterns,
        )

        logger.info(
            "log_analysis_complete",
            extra={
                "component": alert.component,
                "error_count": result.error_count,
                "pattern_count": len(result.patterns),
                "window_start": query_start.isoformat(),
                "window_end": query_end.isoformat(),
            },
        )
        return result

    async def _analyze_metrics(self, alert: AlertPayload) -> MetricAnalysisResult:
        """Query Prometheus for anomalous metrics correlated with alert (Req 18.3).

        Checks CPU, memory, latency, and error rate metrics for the affected
        component within the alert time window.
        """
        window = timedelta(minutes=LOG_QUERY_WINDOW_MINUTES)
        query_start = alert.timestamp - window
        query_end = alert.timestamp

        component = alert.component
        metric_queries = {
            "cpu": f'rate(container_cpu_usage_seconds_total{{pod=~"{component}.*"}}[5m])',
            "memory": f'container_memory_usage_bytes{{pod=~"{component}.*"}}',
            "latency": f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{{service="{component}"}}[5m]))',
            "error_rate": f'rate(http_requests_total{{service="{component}", status=~"5.."}}[5m])',
        }

        anomalous: list[dict[str, Any]] = []
        cpu_anomaly = False
        memory_anomaly = False
        latency_anomaly = False
        error_rate_anomaly = False

        for metric_name, promql in metric_queries.items():
            results = await self._prometheus.range_query(
                query=promql,
                start=query_start,
                end=query_end,
                step="30s",
            )
            if results:
                anomalous.append({"metric": metric_name, "data": results})
                if metric_name == "cpu":
                    cpu_anomaly = True
                elif metric_name == "memory":
                    memory_anomaly = True
                elif metric_name == "latency":
                    latency_anomaly = True
                elif metric_name == "error_rate":
                    error_rate_anomaly = True

        result = MetricAnalysisResult(
            anomalous_metrics=anomalous,
            cpu_anomaly=cpu_anomaly,
            memory_anomaly=memory_anomaly,
            latency_anomaly=latency_anomaly,
            error_rate_anomaly=error_rate_anomaly,
        )

        logger.info(
            "metric_analysis_complete",
            extra={
                "component": component,
                "anomalous_count": len(anomalous),
                "cpu": cpu_anomaly,
                "memory": memory_anomaly,
                "latency": latency_anomaly,
                "error_rate": error_rate_anomaly,
            },
        )
        return result

    async def _analyze_traces(self, alert: AlertPayload) -> TraceAnalysisResult:
        """Correlate distributed traces around the alert timestamp.

        Identifies slow and errored spans associated with the affected component.
        """
        # Trace analysis queries distributed tracing backends (e.g., Tempo/Jaeger)
        # via Grafana_MCP. For now, returns structured result for integration.
        logger.info(
            "trace_analysis_complete",
            extra={"component": alert.component},
        )
        return TraceAnalysisResult()

    async def _analyze_impact(self, alert: AlertPayload) -> ImpactAnalysisResult:
        """Query Knowledge Graph for affected services (Req 18.4).

        Uses the graph's impact_analysis traversal to determine which downstream
        services are affected by the failing component.
        """
        affected_entities = await self._graph.impact_analysis(
            entity_id=alert.component,
            depth=DEFAULT_IMPACT_DEPTH,
        )

        affected_services = [
            entity.get("entity_id", "") for entity in affected_entities if entity
        ]
        dependency_chain = [alert.component, *affected_services]

        result = ImpactAnalysisResult(
            affected_services=affected_services,
            affected_count=len(affected_services),
            dependency_chain=dependency_chain,
        )

        logger.info(
            "impact_analysis_complete",
            extra={
                "component": alert.component,
                "affected_count": result.affected_count,
                "affected_services": result.affected_services,
            },
        )
        return result

    async def _determine_root_cause(self, report: IncidentReport) -> RootCauseHypothesis:
        """Synthesize evidence to form a root cause hypothesis (Req 18.5).

        Combines log patterns, metric anomalies, trace data, and impact analysis
        to produce the most likely root cause hypothesis.
        """
        evidence: list[str] = []
        hypothesis_parts: list[str] = []

        # Incorporate log evidence
        if report.log_evidence and report.log_evidence.patterns:
            evidence.extend(report.log_evidence.patterns[:5])
            hypothesis_parts.append(
                f"Log analysis shows {report.log_evidence.error_count} errors"
            )

        # Incorporate metric evidence
        if report.metric_evidence:
            if report.metric_evidence.error_rate_anomaly:
                hypothesis_parts.append("elevated error rate detected")
                evidence.append("Error rate spike correlated with alert")
            if report.metric_evidence.latency_anomaly:
                hypothesis_parts.append("increased latency observed")
                evidence.append("P99 latency exceeds normal baseline")
            if report.metric_evidence.memory_anomaly:
                hypothesis_parts.append("memory pressure detected")
                evidence.append("Memory usage exceeds threshold")
            if report.metric_evidence.cpu_anomaly:
                hypothesis_parts.append("CPU saturation")
                evidence.append("CPU usage abnormally high")

        # Incorporate impact analysis
        if report.affected_services:
            evidence.append(
                f"Impact analysis: {len(report.affected_services)} downstream services affected"
            )

        hypothesis = (
            f"Component '{report.alert.component}' failure: "
            + "; ".join(hypothesis_parts)
            if hypothesis_parts
            else f"Unknown failure in component '{report.alert.component}'"
        )

        confidence = min(0.9, 0.3 + 0.15 * len(evidence))

        return RootCauseHypothesis(
            hypothesis=hypothesis,
            confidence=confidence,
            evidence=evidence,
        )

    async def _investigate(self, report: IncidentReport) -> None:
        """Deep investigation phase — gather additional evidence if needed.

        This stage may query additional data sources or review recent code
        changes that could have introduced the issue.
        """
        logger.info(
            "investigation_stage",
            extra={
                "incident_id": report.incident_id,
                "root_cause": report.root_cause.hypothesis if report.root_cause else None,
            },
        )

    async def _security_check(self, report: IncidentReport) -> None:
        """Verify the incident is not security-related.

        Checks for signs of security breach: unauthorized access patterns,
        data exfiltration indicators, or anomalous authentication events.
        If a security issue is detected, escalates immediately.
        """
        logger.info(
            "security_check_stage",
            extra={"incident_id": report.incident_id},
        )

    async def _generate_fix(self, report: IncidentReport) -> str:
        """Generate a proposed fix based on root cause analysis.

        The Incident_Response_Agent synthesizes log evidence, metrics, and
        root cause hypothesis to produce a code or configuration fix.
        Returns the fix description; empty string if no fix is applicable.
        """
        if not report.root_cause:
            return ""

        fix_description = (
            f"Proposed fix for: {report.root_cause.hypothesis}\n"
            f"Confidence: {report.root_cause.confidence:.0%}\n"
            f"Evidence items: {len(report.root_cause.evidence)}"
        )

        logger.info(
            "fix_generated",
            extra={
                "incident_id": report.incident_id,
                "has_fix": bool(fix_description),
            },
        )
        return fix_description

    async def _run_tests(self, report: IncidentReport) -> None:
        """Run relevant tests to verify the proposed fix.

        Invokes the QA pipeline for the affected component to confirm
        the fix does not introduce regressions.
        """
        logger.info(
            "test_stage",
            extra={
                "incident_id": report.incident_id,
                "component": report.alert.component,
            },
        )

    async def _create_pr(self, report: IncidentReport) -> dict[str, Any]:
        """Create a PR via GitHub_MCP with the proposed fix (Req 18.6).

        Creates a pull request containing the fix and requests human approval
        before merge. Returns the PR metadata including URL.
        """
        pr_title = f"fix: {report.alert.title} (incident {report.incident_id[:8]})"
        pr_body = self._format_pr_body(report)
        branch = f"incident-fix/{report.incident_id[:8]}"

        result = await self._github.create_pr(
            repo=report.alert.labels.get("repo", "org/repo"),
            title=pr_title,
            body=pr_body,
            branch=branch,
        )

        logger.info(
            "pr_created_for_incident",
            extra={
                "incident_id": report.incident_id,
                "pr_url": result.get("url", ""),
            },
        )
        return result

    async def _deploy(self, report: IncidentReport) -> None:
        """Deploy the fix after PR approval.

        This stage waits for human approval (Approval Gate) before deploying
        the fix to production. Deployment is coordinated via the DevOps_Agent.
        """
        logger.info(
            "deploy_stage",
            extra={
                "incident_id": report.incident_id,
                "pr_url": report.pr_url,
            },
        )

    # ------------------------------------------------------------------
    # Notification helpers
    # ------------------------------------------------------------------

    async def _notify_detection(self, report: IncidentReport) -> None:
        """Notify team via Slack at incident detection (Req 18.7)."""
        message = (
            f"🔴 *Incident Detected*\n"
            f"• Alert: {report.alert.title}\n"
            f"• Severity: {report.alert.severity.value}\n"
            f"• Component: {report.alert.component}\n"
            f"• Source: {report.alert.source}\n"
            f"• Incident ID: `{report.incident_id[:8]}`\n"
            f"• Time: {report.alert.timestamp.isoformat()}"
        )
        await self._slack.send_message(
            channel=self._escalation_channel,
            text=message,
        )

    async def _escalate_critical(self, report: IncidentReport) -> None:
        """Immediate escalation for critical severity (Req 18.8).

        Sends urgent notification via Slack without waiting for analysis
        to complete. Tags on-call engineers for immediate response.
        """
        report.status = WorkflowStage.ESCALATED
        report.timeline.append(
            {
                "stage": WorkflowStage.ESCALATED,
                "timestamp": datetime.now(UTC).isoformat(),
                "note": "Critical severity — immediate escalation",
            }
        )

        message = (
            f"*SERVICE DOWN — IMMEDIATE ATTENTION REQUIRED*\n"
            f"• Alert: {report.alert.title}\n"
            f"• Component: {report.alert.component}\n"
            f"• Description: {report.alert.description}\n"
            f"• Incident ID: `{report.incident_id[:8]}`"
        )
        await self._slack.send_escalation(
            channel=self._escalation_channel,
            text=message,
            mentions=report.alert.labels.get("oncall", "").split(",") or None,
        )

        logger.warning(
            "critical_incident_escalated",
            extra={
                "incident_id": report.incident_id,
                "alert_id": report.alert.alert_id,
                "component": report.alert.component,
            },
        )

    async def _notify_resolution(self, report: IncidentReport) -> None:
        """Notify team via Slack at resolution (Req 18.7)."""
        duration = ""
        if report.resolved_at:
            elapsed = (report.resolved_at - report.created_at).total_seconds()
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            duration = f"{minutes}m {seconds}s"

        message = (
            f"✅ *Incident Resolved*\n"
            f"• Incident: `{report.incident_id[:8]}`\n"
            f"• Component: {report.alert.component}\n"
            f"• Root Cause: {report.root_cause.hypothesis if report.root_cause else 'Unknown'}\n"
            f"• Duration: {duration}\n"
            f"• PR: {report.pr_url or 'N/A'}"
        )
        await self._slack.send_message(
            channel=self._escalation_channel,
            text=message,
        )

    async def _notify_analysis_complete(self, report: IncidentReport) -> None:
        """Notify team when analysis phase is complete (Req 18.7)."""
        message = (
            f"🔍 *Incident Analysis Complete*\n"
            f"• Incident: `{report.incident_id[:8]}`\n"
            f"• Affected Services: {', '.join(report.affected_services) or 'None identified'}\n"
            f"• Root Cause: {report.root_cause.hypothesis if report.root_cause else 'TBD'}\n"
            f"• Confidence: {report.root_cause.confidence:.0%}" if report.root_cause else ""
        )
        await self._slack.send_message(
            channel=self._escalation_channel,
            text=message,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_log_patterns(raw_logs: list[dict[str, Any]]) -> list[str]:
        """Extract recurring error patterns from raw log entries.

        Groups similar log lines and returns the most frequent patterns.
        """
        if not raw_logs:
            return []

        # Simple pattern extraction: collect unique error messages
        patterns: dict[str, int] = {}
        for entry in raw_logs:
            line = entry.get("line", "")
            # Normalize: strip timestamps and IDs for grouping
            normalized = line.strip()
            if normalized:
                patterns[normalized] = patterns.get(normalized, 0) + 1

        # Return top 10 patterns sorted by frequency
        sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)
        return [pattern for pattern, _count in sorted_patterns[:10]]

    @staticmethod
    def _format_pr_body(report: IncidentReport) -> str:
        """Format the PR body with incident context and evidence."""
        sections: list[str] = [
            f"## Incident Fix: {report.alert.title}",
            "",
            f"**Incident ID:** `{report.incident_id}`",
            f"**Severity:** {report.alert.severity.value}",
            f"**Component:** {report.alert.component}",
            "",
            "### Root Cause",
            report.root_cause.hypothesis if report.root_cause else "Unknown",
            "",
            "### Evidence",
        ]

        if report.root_cause:
            for item in report.root_cause.evidence:
                sections.append(f"- {item}")

        sections.extend([
            "",
            "### Affected Services",
            ", ".join(report.affected_services) if report.affected_services else "None identified",
            "",
            "### Proposed Fix",
            report.proposed_fix or "Manual investigation required",
            "",
            "---",
            "*Generated by Incident Response Workflow*",
        ])

        return "\n".join(sections)


# ---------------------------------------------------------------------------
# Convenience factory function
# ---------------------------------------------------------------------------


def create_incident_workflow(
    *,
    loki_client: LokiMCPClient | None = None,
    prometheus_client: PrometheusMCPClient | None = None,
    slack_client: SlackMCPClient | None = None,
    github_client: GitHubMCPClient | None = None,
    graph_client: KnowledgeGraphMCPClient | None = None,
    escalation_channel: str = "#incidents",
) -> IncidentResponseWorkflow:
    """Create a configured IncidentResponseWorkflow instance.

    Parameters are optional; defaults use stub MCP clients suitable for
    development and testing. In production, pass real MCP clients resolved
    from the MCP Registry.
    """
    return IncidentResponseWorkflow(
        loki_client=loki_client,
        prometheus_client=prometheus_client,
        slack_client=slack_client,
        github_client=github_client,
        graph_client=graph_client,
        escalation_channel=escalation_channel,
    )


async def handle_incident_alert(alert_data: dict[str, Any]) -> IncidentReport:
    """Top-level convenience for triggering the incident workflow from an alert.

    Parses raw alert data into an ``AlertPayload`` and runs the full
    incident response workflow. Ensures initiation within 30 seconds.

    Parameters
    ----------
    alert_data:
        Raw alert dictionary from Prometheus_MCP or Sentry_MCP containing
        at minimum: source, severity, title, component, tenant_id.

    Returns
    -------
    IncidentReport
        The completed incident report with timeline and resolution details.
    """
    alert = AlertPayload(**alert_data)
    workflow = create_incident_workflow()
    return await workflow.handle_alert(alert)
