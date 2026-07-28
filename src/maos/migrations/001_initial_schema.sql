-- 001_initial_schema.sql
-- Multi-Agent Orchestration System (MAOS) — Initial Postgres Schema
-- Requirements: 10.3, 13.2, 3.1, 16.4, 16.6

BEGIN;

-- =============================================================================
-- Agent Registry (Req 4, 13)
-- =============================================================================

CREATE TABLE agent_registry (
    subagent_id       TEXT PRIMARY KEY,
    role              TEXT NOT NULL,
    platform_system   TEXT NOT NULL,
    mode              TEXT NOT NULL CHECK (mode IN ('DEVELOPMENT', 'RUNTIME')),
    capability        JSONB NOT NULL,        -- {max_reasoning_steps, max_tool_invocations}
    mcp_allow_list    JSONB NOT NULL,
    status            TEXT NOT NULL DEFAULT 'available',
    selection_priority INT NOT NULL DEFAULT 0,
    UNIQUE (role, platform_system, mode)
);

CREATE TABLE skill (
    skill_id          TEXT NOT NULL,
    subagent_id       TEXT NOT NULL REFERENCES agent_registry(subagent_id),
    input_contract    JSONB NOT NULL,
    output_contract   JSONB NOT NULL,
    operation_scope   JSONB NOT NULL,
    PRIMARY KEY (subagent_id, skill_id)   -- duplicate skill per role/platform rejected (Req 13.2)
);

-- =============================================================================
-- Work Units with Traceability (Req 1-3)
-- =============================================================================

CREATE TABLE task (
    task_id       TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    requester_id  TEXT NOT NULL,
    mode          TEXT NOT NULL,
    auth_scope    JSONB NOT NULL,
    payload       JSONB NOT NULL,
    token_budget  INT NOT NULL,
    state         TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE subtask (
    subtask_id       TEXT PRIMARY KEY,
    task_id          TEXT NOT NULL REFERENCES task(task_id),
    platform_system  TEXT NOT NULL,
    mode             TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    state            TEXT NOT NULL,
    input_contract   JSONB NOT NULL
);

CREATE INDEX ix_subtask_task ON subtask(task_id);

CREATE TABLE sub_subtask (
    sub_subtask_id       TEXT PRIMARY KEY,
    subtask_id           TEXT NOT NULL REFERENCES subtask(subtask_id),
    task_id              TEXT NOT NULL REFERENCES task(task_id),     -- denormalized for trace (Req 3.1)
    platform_system      TEXT NOT NULL,
    mode                 TEXT NOT NULL,
    tenant_id            TEXT NOT NULL,
    required_skill       TEXT NOT NULL,
    assigned_subagent_id TEXT,
    is_sensitive         BOOLEAN NOT NULL DEFAULT FALSE,
    attempts             INT NOT NULL DEFAULT 0,
    state                TEXT NOT NULL
);

CREATE INDEX ix_subsub_subtask ON sub_subtask(subtask_id);

-- =============================================================================
-- Append-Only Audit Log (Req 10.3)
-- Enforced by DB grants (see 002_audit_grants.sql), not app logic.
-- =============================================================================

CREATE TABLE audit_log (
    audit_id         BIGSERIAL PRIMARY KEY,
    task_id          TEXT NOT NULL,
    subtask_id       TEXT,
    sub_subtask_id   TEXT,
    actor_agent_id   TEXT,
    event_type       TEXT NOT NULL,
    detail           JSONB NOT NULL,       -- redacted: no secrets/PHI (Req 5.6, 9.5)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE audit_log IS 'Append-only audit trail. Application role granted INSERT/SELECT only — no UPDATE/DELETE (Req 10.3).';

CREATE INDEX ix_audit_task ON audit_log(task_id);
CREATE INDEX ix_audit_subtask ON audit_log(subtask_id);

-- =============================================================================
-- Cost Metering (Req 10.8, 8.5)
-- =============================================================================

CREATE TABLE cost_meter (
    id          BIGSERIAL PRIMARY KEY,
    task_id     TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    tokens      INT NOT NULL,
    cost_usd    NUMERIC(12,6) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

-- =============================================================================
-- Human Approvals (Req 11.7, 11.8)
-- =============================================================================

CREATE TABLE approval (
    approval_id      TEXT PRIMARY KEY,
    sub_subtask_id   TEXT NOT NULL,
    requested_at     TIMESTAMPTZ NOT NULL,
    window_s         INT NOT NULL,
    decision         TEXT,                  -- approved | denied | expired | NULL (pending)
    approver_id      TEXT,
    decided_at       TIMESTAMPTZ
);

-- =============================================================================
-- Peer Delegation Lineage and Depth (Req 16)
-- =============================================================================

CREATE TABLE delegated_work (
    delegated_work_id      TEXT PRIMARY KEY,
    delegation_id          TEXT NOT NULL,
    origin_sub_subtask_id  TEXT NOT NULL REFERENCES sub_subtask(sub_subtask_id),  -- traceable (Req 16.4)
    subtask_id             TEXT NOT NULL REFERENCES subtask(subtask_id),          -- traceable (Req 16.4)
    task_id                TEXT NOT NULL REFERENCES task(task_id),                -- traceable (Req 16.4)
    delegating_subagent_id TEXT NOT NULL,
    peer_subagent_id       TEXT NOT NULL,
    tenant_id              TEXT NOT NULL,                                         -- isolation (Req 16.3)
    mode                   TEXT NOT NULL CHECK (mode IN ('DEVELOPMENT', 'RUNTIME')),
    depth                  INT NOT NULL,   -- hops for this unit; <= Max_Delegation_Depth (Req 16.6)
    state                  TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_delegated_origin ON delegated_work(origin_sub_subtask_id);
CREATE INDEX ix_delegated_task ON delegated_work(task_id);

COMMIT;
