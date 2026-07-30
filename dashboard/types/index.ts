// types/index.ts
// Shared TypeScript types for the MAOS Dashboard

// --- Work Units (mirrors MAOS contracts) ---

/** Operating mode determines whether agents run in development or production context. */
export type OperatingMode = "DEVELOPMENT" | "RUNTIME";

/** Platform system identifies the technology domain a work unit targets. */
export type PlatformSystem = "BACKEND" | "WEB" | "MOBILE";

/** Lifecycle state of a work unit (Task, Subtask, or Sub_Subtask). */
export type WorkUnitState =
  | "assigned"
  | "in_progress"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "timed_out"
  | "permanently_failed";

/**
 * A top-level task submitted to the MAOS orchestration system.
 * Contains metadata, budget constraints, and lifecycle timestamps.
 */
export interface Task {
  /** Unique identifier for the task. */
  task_id: string;
  /** Tenant that owns this task. */
  tenant_id: string;
  /** User or system that submitted this task. */
  requester_id: string;
  /** Operating mode (DEVELOPMENT or RUNTIME). */
  mode: OperatingMode;
  /** Human-readable title of the task. */
  title: string;
  /** Detailed description of the task objective. */
  description: string;
  /** Current lifecycle state. */
  state: WorkUnitState;
  /** Maximum token budget allocated for this task. */
  token_budget: number;
  /** Total tokens consumed so far. */
  tokens_consumed: number;
  /** ISO 8601 timestamp of task creation. */
  created_at: string;
  /** ISO 8601 timestamp of last state update. */
  updated_at: string;
}

/**
 * A subtask routed to a platform-specific sub-orchestrator.
 * Created by the root orchestrator during task decomposition.
 */
export interface Subtask {
  /** Unique identifier for the subtask. */
  subtask_id: string;
  /** Parent task identifier. */
  task_id: string;
  /** Target platform system (BACKEND, WEB, or MOBILE). */
  platform_system: PlatformSystem;
  /** Operating mode inherited or overridden from parent task. */
  mode: OperatingMode;
  /** Current lifecycle state. */
  state: WorkUnitState;
  /** Sub-orchestrator assigned to execute this subtask. */
  assigned_orchestrator_id: string;
  /** ISO 8601 timestamp when execution started. */
  started_at?: string;
  /** ISO 8601 timestamp when execution completed. */
  completed_at?: string;
}

/**
 * A sub-subtask assigned to an individual subagent.
 * The most granular work unit in the MAOS hierarchy.
 */
export interface SubSubtask {
  /** Unique identifier for the sub-subtask. */
  sub_subtask_id: string;
  /** Parent subtask identifier. */
  subtask_id: string;
  /** Root task identifier for tracing. */
  task_id: string;
  /** Target platform system. */
  platform_system: PlatformSystem;
  /** Operating mode. */
  mode: OperatingMode;
  /** Skill required to execute this work unit. */
  required_skill: string;
  /** Subagent assigned to execute, if any. */
  assigned_subagent_id?: string;
  /** Current lifecycle state. */
  state: WorkUnitState;
  /** Whether this sub-subtask handles sensitive (e.g. PHI) data. */
  is_sensitive: boolean;
  /** Number of execution attempts made. */
  attempts: number;
  /** ISO 8601 timestamp when execution started. */
  started_at?: string;
  /** ISO 8601 timestamp when execution completed. */
  completed_at?: string;
}

// --- Agent Hierarchy ---

/**
 * A single agent node in the MAOS hierarchy.
 * Represents a subagent with its capabilities, status, and assignments.
 */
export interface AgentNode {
  /** Unique identifier for the agent. */
  agent_id: string;
  /** Role descriptor for the agent. */
  role: string;
  /** Platform system this agent operates within. */
  platform_system: PlatformSystem;
  /** Operating mode (DEVELOPMENT or RUNTIME). */
  mode: OperatingMode;
  /** Current availability status. */
  status: "available" | "draining" | "removed";
  /** List of declared skills this agent can perform. */
  skills: string[];
  /** Maximum reasoning steps allowed per execution. */
  max_reasoning_steps: number;
  /** Maximum tool invocations allowed per execution. */
  max_tool_invocations: number;
  /** Allowed MCP server names this agent can invoke. */
  mcp_allow_list: string[];
  /** Selection priority for deterministic agent selection. */
  selection_priority: number;
  /** Currently active sub_subtask assignments (sub_subtask_ids). */
  active_assignments: string[];
}

/**
 * Hierarchical tree representation of the entire agent topology.
 * Root Orchestrator -> Sub-Orchestrators -> Subagents.
 */
export interface AgentTree {
  /** Root orchestrator node. */
  root: { id: string; status: string };
  /** Platform-specific sub-orchestrators with their assigned subagents. */
  sub_orchestrators: {
    /** Platform system this sub-orchestrator manages. */
    platform_system: PlatformSystem;
    /** Sub-orchestrator identifier. */
    id: string;
    /** Current status of the sub-orchestrator. */
    status: string;
    /** Subagents managed by this sub-orchestrator. */
    subagents: AgentNode[];
  }[];
}

// --- Cost Records ---

/**
 * A single cost record representing token consumption for an LLM call.
 * Tracks cost attribution across agent, task, tenant, and provider dimensions.
 */
export interface CostRecord {
  /** Unique identifier for this cost record. */
  record_id: string;
  /** Task that incurred this cost. */
  task_id: string;
  /** Agent that made the LLM call. */
  agent_id: string;
  /** Tenant billed for this cost. */
  tenant_id: string;
  /** LLM provider name (e.g., Anthropic, OpenAI, Bedrock, Vertex). */
  provider: string;
  /** Model identifier used for the call. */
  model: string;
  /** Number of tokens consumed. */
  tokens: number;
  /** Estimated cost in USD. */
  cost_usd: number;
  /** ISO 8601 timestamp when the cost was recorded. */
  timestamp: string;
}

/**
 * Aggregated cost data grouped by a single dimension.
 * Used for summary views and cost breakdown displays.
 */
export interface CostAggregation {
  /** The dimension used for grouping (agent_id, task_id, tenant_id, provider). */
  dimension: string;
  /** The specific value within the dimension. */
  key: string;
  /** Total tokens consumed across all records in this group. */
  total_tokens: number;
  /** Total cost in USD across all records in this group. */
  total_cost_usd: number;
}

// --- Audit ---

/** Event types tracked in the MAOS audit log. */
export type AuditEventType =
  | "routing_decision"
  | "tool_invocation"
  | "approval_request"
  | "approval_decision"
  | "delegation"
  | "error"
  | "access_denial"
  | "phi_redaction"
  | "sandbox_violation";

/**
 * A single audit log entry recording a system event.
 * Provides full traceability for compliance and debugging.
 */
export interface AuditEntry {
  /** Unique identifier for this audit entry. */
  entry_id: string;
  /** ISO 8601 timestamp of when the event occurred. */
  timestamp: string;
  /** Classification of the audit event. */
  event_type: AuditEventType;
  /** Task associated with this event. */
  task_id: string;
  /** Subtask associated with this event, if applicable. */
  subtask_id?: string;
  /** Sub-subtask associated with this event, if applicable. */
  sub_subtask_id?: string;
  /** Agent involved in this event, if applicable. */
  agent_id?: string;
  /** Tenant that owns the resource involved. */
  tenant_id: string;
  /** Human-readable summary of the event. */
  summary: string;
  /** Structured detail payload with event-specific metadata. */
  detail: Record<string, unknown>;
}

// --- WebSocket ---

/** Connection state of the WebSocket to the MAOS backend. */
export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

/**
 * A real-time event received over the WebSocket connection.
 * Carries topic-scoped updates for dashboard sections.
 */
export interface WSEvent {
  /** Topic channel (e.g., tasks.*, agents.*, costs.*). */
  topic: string;
  /** Specific event type within the topic. */
  event_type: string;
  /** Event payload with event-specific data. */
  payload: Record<string, unknown>;
  /** ISO 8601 timestamp of the event. */
  timestamp: string;
}

// --- Health ---

/**
 * Health status of an individual MAOS infrastructure service.
 * Reported by the health monitoring subsystem.
 */
export interface ServiceHealth {
  /** Service name (e.g., API workers, Arq workers, Postgres, Dragonfly). */
  service: string;
  /** Current health status. */
  status: "healthy" | "degraded" | "unavailable";
  /** Response latency in milliseconds from last health check. */
  latency_ms?: number;
  /** ISO 8601 timestamp of the last health check. */
  last_check: string;
}

/**
 * Status of a registered MCP (Model Context Protocol) server.
 * Includes connectivity health and failure tracking.
 */
export interface MCPServerStatus {
  /** Display name of the MCP server. */
  name: string;
  /** Network endpoint for the MCP server. */
  endpoint: string;
  /** Current health status. */
  status: "healthy" | "degraded" | "unavailable";
  /** Number of consecutive health check failures. */
  consecutive_failures: number;
  /** ISO 8601 timestamp of the last health check. */
  last_check: string;
  /** Response latency in milliseconds. */
  latency_ms?: number;
}

// --- Knowledge ---

/**
 * A Knowledge Base namespace representing a logical document collection.
 * Namespaces provide tenant and role-scoped document isolation.
 */
export interface KBNamespace {
  /** Namespace identifier. */
  namespace: string;
  /** Tenant that owns this namespace. */
  tenant_id: string;
  /** Role scope for access control. */
  role: string;
  /** Number of documents in this namespace. */
  document_count: number;
  /** Total tokens across all documents in this namespace. */
  total_tokens: number;
}

/**
 * A document stored in the Knowledge Base.
 * Contains metadata about the ingested file and its chunking.
 */
export interface KBDocument {
  /** Unique identifier for the document. */
  document_id: string;
  /** Namespace this document belongs to. */
  namespace: string;
  /** Original filename of the uploaded document. */
  filename: string;
  /** MIME type or file extension. */
  file_type: string;
  /** Number of chunks the document was split into. */
  chunk_count: number;
  /** Total tokens across all chunks. */
  total_tokens: number;
  /** ISO 8601 timestamp of when the document was uploaded. */
  uploaded_at: string;
  /** Identifier of the user or system that uploaded the document. */
  uploader_id: string;
}

// --- Filtering & Sorting ---

/**
 * Filter criteria for the task list view.
 * All active criteria are combined with AND logic.
 */
export interface TaskFilter {
  /** Filter by one or more work unit states. */
  state?: WorkUnitState[];
  /** Filter by one or more platform systems. */
  platform_system?: PlatformSystem[];
  /** Filter by one or more operating modes. */
  mode?: OperatingMode[];
  /** Filter by specific tenant identifier. */
  tenant_id?: string;
}

/**
 * Sort configuration for ordered list displays.
 * Specifies the field to sort by and the direction.
 */
export interface SortConfig {
  /** Field name to sort by. */
  field: string;
  /** Sort direction: ascending or descending. */
  direction: "asc" | "desc";
}

/**
 * Pagination parameters for paginated API requests and local slicing.
 * Uses offset-based pagination.
 */
export interface PaginationParams {
  /** Zero-based offset into the result set. */
  offset: number;
  /** Maximum number of items to return. */
  limit: number;
}

/**
 * Generic paginated response wrapper.
 * Contains a page of items along with pagination metadata.
 */
export interface PaginatedResponse<T> {
  /** Items in the current page. */
  items: T[];
  /** Total number of items across all pages. */
  total_count: number;
  /** Effective offset used (clamped to valid range). */
  offset: number;
  /** Effective limit used. */
  limit: number;
}
