# MAOS — Multi-Agent Orchestration System

> A production-grade, standalone Python service that coordinates a hierarchical set of AI agents
> to perform engineering and runtime work across the Healthcare platform.
> Built for ~500,000 users with horizontal autoscaling, multi-tenant isolation, and PHI compliance.

---

## Table of Contents

1. [What is MAOS?](#what-is-maos)
2. [How It Works — The Big Picture](#how-it-works--the-big-picture)
3. [Architecture Diagrams](#architecture-diagrams)
4. [Prerequisites](#prerequisites)
5. [Step-by-Step Setup (Local Development)](#step-by-step-setup-local-development)
6. [Step-by-Step Setup (Production / Kubernetes)](#step-by-step-setup-production--kubernetes)
7. [How to Use MAOS — Complete Workflow](#how-to-use-maos--complete-workflow)
8. [API Reference (All Endpoints)](#api-reference-all-endpoints)
9. [Operating Modes Explained](#operating-modes-explained)
10. [Subagent Roster — Who Does What](#subagent-roster--who-does-what)
11. [How to Add Custom Agents](#how-to-add-custom-agents)
12. [How to Add Custom MCP Tools](#how-to-add-custom-mcp-tools)
13. [Security Model — Deep Dive](#security-model--deep-dive)
14. [Observability — Monitoring Your Agents](#observability--monitoring-your-agents)
15. [Cost Controls and Budgets](#cost-controls-and-budgets)
16. [Resilience and Fault Tolerance](#resilience-and-fault-tolerance)
17. [Configuration Reference](#configuration-reference)
18. [Project Structure](#project-structure)
19. [Troubleshooting](#troubleshooting)
20. [FAQ](#faq)

---

## What is MAOS?

MAOS (Multi-Agent Orchestration System) is a **standalone microservice** that sits alongside your Healthcare platform and coordinates AI agents to do work on your behalf. Think of it as an intelligent dispatcher that:

1. **Receives a high-level task** from any of your platform systems (backend, web, or mobile)
2. **Breaks it down** into smaller pieces, each targeting the right platform
3. **Assigns specialized agents** (code reviewers, debuggers, security analysts, feature builders) to each piece
4. **Monitors execution**, handles failures, and reassigns work if needed
5. **Aggregates results** and returns them to you

It is NOT embedded in your NestJS backend. It runs as a separate service that your systems call via REST API.

### Real-World Examples

| You Say (Task) | MAOS Does |
|----------------|-----------|
| "Review the authentication module for security issues" | Routes to Security_Subagent (Backend), runs analysis via MCP tools, returns findings |
| "Debug why the mobile app crashes on login" | Routes to Debugger (Mobile), examines crash logs + code, suggests fix |
| "Implement user profile photo upload" | Decomposes across Backend (API) + Web (UI) + Mobile (UI), routes to Feature_Implementers |
| "Help patient reschedule their appointment" | RUNTIME mode → routes to Appointment_Assistant, interacts with live booking API |

---

## How It Works — The Big Picture

### The Three-Level Hierarchy

```
YOU (Platform System)
  │
  │  POST /v1/tasks  { mode: "DEVELOPMENT", title: "Fix login bug", ... }
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│                    ROOT ORCHESTRATOR                          │
│                                                              │
│  1. Validates your task                                      │
│  2. Classifies which platform(s) are involved                │
│  3. Decomposes into Subtasks (one per platform)              │
│  4. Routes each Subtask to the correct Sub-Orchestrator      │
└────────┬─────────────────┬─────────────────┬────────────────┘
         │                 │                 │
   ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
   │ BACKEND   │    │   WEB     │    │  MOBILE   │
   │ Sub-Orch  │    │ Sub-Orch  │    │ Sub-Orch  │
   │           │    │           │    │           │
   │ Breaks    │    │ Breaks    │    │ Breaks    │
   │ into      │    │ into      │    │ into      │
   │ SubSub-   │    │ SubSub-   │    │ SubSub-   │
   │ tasks     │    │ tasks     │    │ tasks     │
   └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
         │                 │                 │
   ┌─────▼─────────────────▼─────────────────▼─────┐
   │              SUBAGENT POOL                      │
   │                                                 │
   │  Code_Reviewer    Debugger    Security          │
   │  Feature_Impl     Appointment_Asst  Billing    │
   │                                                 │
   │  Each agent has:                                │
   │  • Declared Skills (what it can do)             │
   │  • Bounded budgets (max reasoning steps)        │
   │  • MCP tools allow-list (what it can use)       │
   │  • Operating mode (DEV or RUNTIME)              │
   └─────────────────────────────────────────────────┘
```

### What Happens Step by Step

1. **Your system** sends `POST /v1/tasks` with a task description
2. **API layer** authenticates, rate-limits, checks backpressure, enqueues
3. **Arq worker** picks up the task from the Redis broker queue
4. **Root Orchestrator** (LangGraph graph) validates, classifies, decomposes
5. **Sub-Orchestrator** selects the best agent by skill+mode+priority
6. **Subagent** executes using bounded reasoning + MCP tools (sandboxed)
7. **Results flow back up** through aggregation at each level
8. **You poll** `GET /v1/tasks/{id}` to get the final result

Every single step is checkpointed to Postgres. If a worker crashes, another one picks up exactly where it left off.

---

## Architecture Diagrams

### Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        KUBERNETES CLUSTER                             │
│                                                                       │
│  ┌──────────────┐    ┌───────────────────┐    ┌──────────────────┐  │
│  │   Ingress    │    │   API Pods (HPA)  │    │  Worker Pods     │  │
│  │  (TLS+Auth   │───▶│   FastAPI x2-10   │    │  (KEDA) x2-20   │  │
│  │  +RateLimit) │    │   Port 8000       │    │  Arq workers     │  │
│  └──────────────┘    └────────┬──────────┘    └───────┬──────────┘  │
│                               │                       │              │
│                    ┌──────────▼───────────────────────▼──────────┐   │
│                    │              PgBouncer (x2)                  │   │
│                    │         Connection pooling                   │   │
│                    └──────────────────┬──────────────────────────┘   │
│                                       │                              │
│  ┌────────────────┐  ┌───────────────▼───────┐  ┌───────────────┐  │
│  │   Redis /      │  │      Postgres         │  │   Sandbox     │  │
│  │   Dragonfly    │  │  (checkpoints, audit, │  │   Pool (x3)   │  │
│  │                │  │   registry, pgvector) │  │   gVisor       │  │
│  └────────────────┘  └───────────────────────┘  └───────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  External: LLM Providers (Anthropic/OpenAI/Bedrock/Vertex)     │  │
│  │  External: Vault (secrets) · OTel Collector · Sentry           │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow for a Single Task

```
Client ──POST /v1/tasks──▶ API Pod
                              │
                    [validate + backpressure check]
                              │
                    [enqueue to Redis broker]
                              │
                              ▼
                         Arq Worker
                              │
                    [load from checkpoint if resuming]
                              │
                    ┌─────────▼─────────┐
                    │ Root Orchestrator  │──▶ Audit_Log
                    │   (LangGraph)     │──▶ Shared_Context
                    └────────┬──────────┘──▶ Cost_Meter
                             │
                    [decompose into Subtasks]
                             │
                    ┌────────▼──────────┐
                    │ Sub-Orchestrator   │
                    │  (select agent)    │
                    └────────┬──────────┘
                             │
                    ┌────────▼──────────┐
                    │    Subagent        │
                    │  (reasoning loop)  │
                    │     │              │
                    │     ├──▶ LLM call (via adapter)
                    │     ├──▶ MCP tool (via gateway)
                    │     │      └──▶ Sandbox (if code)
                    │     └──▶ Human_Approval (if sensitive)
                    └────────┬──────────┘
                             │
                    [aggregate results upward]
                             │
                             ▼
                    Result stored in DB
                              │
Client ──GET /v1/tasks/{id}──┘
```

---

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.12+ | Runtime |
| uv | latest | Package management (fast pip alternative) |
| Postgres | 15+ | Primary database (checkpoints, audit, registry, code graph) |
| pgvector extension | 0.5+ | Semantic_Memory vector search |
| Dragonfly | latest | Shared_Context, message bus, broker (Redis-compatible) |
| Docker | 24+ | Container builds |
| kubectl | 1.28+ | Kubernetes deployment (production) |

### Optional Software

| Software | Purpose |
|----------|---------|
| HashiCorp Vault | Production secrets management |
| KEDA | Kubernetes event-driven autoscaling for workers |
| gVisor (runsc) | Sandbox isolation for code execution |

### Required Accounts / API Keys

| Service | Required For | How to Get |
|---------|-------------|-----------|
| Anthropic | Default LLM (Claude) | https://console.anthropic.com |
| OpenAI | Fallback LLM | https://platform.openai.com |
| AWS (Bedrock) | PHI-compliant LLM calls | AWS Console |
| Sentry | Error reporting | https://sentry.io |
| LangSmith OR Langfuse | Agent tracing | https://smith.langchain.com or https://langfuse.com |

---

## Step-by-Step Setup (Local Development)

### Step 1: Clone and Enter the Project

```bash
cd Healthcare/
cd maos/
```

### Step 2: Install uv (if not already installed)

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Step 3: Install All Dependencies

```bash
# Install runtime + dev dependencies
uv sync --all-extras

# Verify installation
uv run python -c "import maos; print('MAOS installed successfully')"
```

### Step 4: Start Postgres with pgvector

```bash
# Using Docker (easiest):
docker run -d \
  --name maos-postgres \
  -e POSTGRES_USER=maos \
  -e POSTGRES_PASSWORD=maos \
  -e POSTGRES_DB=maos \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### Step 5: Start Dragonfly (Redis-compatible)

```bash
# Using Docker:
docker run -d \
  --name maos-dragonfly \
  -p 6379:6379 \
  docker.dragonflydb.io/dragonflydb/dragonfly:latest
```

### Step 6: Configure Environment Variables

Create a `.env` file in the `maos/` directory:

```bash
# .env — Local development configuration

# === Database ===
MAOS_POSTGRES_DSN=postgresql://maos:maos@localhost:5432/maos

# === Redis ===
MAOS_REDIS_URL=redis://localhost:6379/0
MAOS_BROKER_URL=redis://localhost:6379/1
MAOS_DRAGONFLY_CACHE_URL=redis://localhost:6379/2

# === LLM Providers (at minimum, set one) ===
ANTHROPIC_API_KEY=<your-anthropic-api-key>
# OPENAI_API_KEY=<your-openai-api-key>
# AWS_REGION=us-east-1

# === Secrets Backend ===
SECRETS_BACKEND=env

# === Observability (optional for local dev) ===
# SENTRY_DSN=https://your-dsn@sentry.io/project-id
# LANGSMITH_API_KEY=ls-your-key
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# === Budgets ===
MAOS_DEFAULT_TASK_TOKEN_BUDGET=100000
MAOS_TENANT_DAILY_TOKEN_CEILING=5000000

# === Concurrency ===
MAOS_GLOBAL_CONCURRENCY_CAP=100
MAOS_TENANT_CONCURRENCY_CAP=10
```

### Step 7: Run Database Migrations

```bash
uv run python -m maos.migrations.run
```

You should see:
```
INFO: Connecting to database for migrations...
INFO: Applying migration: 001_initial_schema.sql
INFO: Applying migration: 002_audit_grants.sql
INFO: Applying migration: 003_approval_task_id.sql
INFO: Migration complete: 3 migration(s) applied successfully.
```

### Step 8: Start the API Server

```bash
uv run uvicorn maos.api.app:create_app --factory --reload --port 8000
```

Verify it's running:
```bash
curl http://localhost:8000/healthz
# → {"status": "ok"}
```

### Step 9: Start the Arq Workers (separate terminal)

```bash
uv run arq maos.workers.orchestration.OrchestrationWorkerSettings
```

You should see:
```
INFO: Orchestration worker started
```

### Step 10: Submit Your First Task

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -H "X-Tenant-Id: clinic-001" \
  -H "X-Auth-Scope: tasks:write" \
  -d '{
    "mode": "DEVELOPMENT",
    "title": "Review login authentication",
    "description": "Security review of the login flow in the backend",
    "payload": {
      "target_system": "BACKEND",
      "scope": ["src/auth/"]
    },
    "token_budget": 50000
  }'
```

Response:
```json
{
  "task_id": "a1b2c3d4-...",
  "status": "accepted"
}
```

### Step 11: Check Task Status

```bash
curl http://localhost:8000/v1/tasks/a1b2c3d4-... \
  -H "Authorization: Bearer dev-token"
```

---

## Step-by-Step Setup (Production / Kubernetes)

### Step 1: Build Container Images

```bash
cd maos/

# Build API image
docker build -f Dockerfile.api -t maos-api:0.1.0 .

# Build Worker image
docker build -f Dockerfile.worker -t maos-worker:0.1.0 .

# Build Sandbox image
docker build -f Dockerfile.sandbox -t maos-sandbox:0.1.0 .

# Push to your registry
docker tag maos-api:0.1.0 your-registry.io/maos-api:0.1.0
docker push your-registry.io/maos-api:0.1.0
# ... repeat for worker and sandbox
```

### Step 2: Configure Secrets in Vault

Set up your secrets in HashiCorp Vault (or AWS Secrets Manager):

```bash
# Example: Vault KV v2
vault kv put maos/database password="your-strong-password"
vault kv put maos/llm \
  anthropic_api_key="<your-anthropic-key>" \
  openai_api_key="<your-openai-key>" \
  google_api_key="<your-google-key>"
vault kv put maos/redis password="redis-auth-token"
vault kv put maos/aws \
  access_key_id="AKIA..." \
  secret_access_key="..."
vault kv put maos/observability sentry_dsn="https://..."
vault kv put maos/auth \
  jwks_url="https://your-idp/.well-known/jwks.json" \
  issuer="https://your-idp"
```

### Step 3: Update ConfigMap Values

Edit `k8s/configmap.yaml` with your actual infrastructure endpoints:

```yaml
data:
  MAOS_POSTGRES_HOST: "your-postgres-host.rds.amazonaws.com"
  MAOS_REDIS_URL: "redis://your-redis-cluster:6379/0"
  MAOS_BROKER_URL: "redis://your-redis-cluster:6379/1"
  # ... update all values for your environment
```

### Step 4: Deploy to Kubernetes (in order)

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Deploy configuration
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml

# 3. Deploy PgBouncer (connection pooling)
kubectl apply -f k8s/pgbouncer-deployment.yaml

# 4. Run database migrations (wait for completion)
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete job/maos-db-migration -n maos --timeout=120s

# 5. Deploy API
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/api-hpa.yaml

# 6. Deploy Workers
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/worker-hpa.yaml

# 7. Deploy Sandbox pool
kubectl apply -f k8s/sandbox-deployment.yaml

# 8. Apply Network Policies (security)
kubectl apply -f k8s/network-policy.yaml

# 9. Deploy Ingress (external access)
kubectl apply -f k8s/ingress.yaml

# 10. Deploy retention sweeper CronJob
kubectl apply -f k8s/retention-cronjob.yaml
```

### Step 5: Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n maos

# Check API health
kubectl port-forward svc/maos-api 8000:8000 -n maos
curl http://localhost:8000/healthz

# Check logs
kubectl logs -l app.kubernetes.io/name=maos-api -n maos --tail=50
kubectl logs -l app.kubernetes.io/name=maos-worker -n maos --tail=50
```

---

## How to Use MAOS — Complete Workflow

### Use Case 1: Code Review (DEVELOPMENT Mode)

**Scenario:** You want MAOS to review the authentication module for security issues.

```bash
# Step 1: Submit the task
curl -X POST https://maos.your-domain.io/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: clinic-001" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "DEVELOPMENT",
    "title": "Security review of auth module",
    "description": "Review the authentication middleware in the NestJS backend for vulnerabilities including: injection attacks, broken authentication, session management issues",
    "payload": {
      "target_system": "BACKEND",
      "scope": ["src/auth/", "src/middleware/"],
      "review_type": "security"
    },
    "token_budget": 80000
  }'

# Response: { "task_id": "01JFGK...", "status": "accepted" }

# Step 2: Poll for completion (or use webhooks)
curl https://maos.your-domain.io/v1/tasks/01JFGK... \
  -H "Authorization: Bearer $TOKEN"

# Response when done:
# {
#   "task_id": "01JFGK...",
#   "state": "completed",
#   "result": {
#     "subtask_results": [{
#       "platform_system": "BACKEND",
#       "sub_subtask_results": [{
#         "agent": "Security_Subagent_Backend",
#         "findings": [...],
#         "severity": "medium",
#         "recommendations": [...]
#       }]
#     }]
#   }
# }
```

### Use Case 2: Multi-Platform Feature (DEVELOPMENT Mode)

**Scenario:** Implement user profile photo upload across all platforms.

```bash
curl -X POST https://maos.your-domain.io/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: clinic-001" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "DEVELOPMENT",
    "title": "Implement profile photo upload",
    "description": "Add user profile photo upload: backend API endpoint for S3 upload, web UI with drag-drop, mobile UI with camera/gallery picker",
    "payload": {
      "target_systems": ["BACKEND", "WEB", "MOBILE"],
      "requirements": "Max 5MB, JPEG/PNG only, crop to square, store in S3"
    },
    "token_budget": 200000
  }'

# MAOS will:
# 1. Decompose into 3 Subtasks (one per platform)
# 2. Assign Feature_Implementer (Backend) → API endpoint
# 3. Assign Feature_Implementer (Web) → React drag-drop UI
# 4. Assign Feature_Implementer (Mobile) → Expo camera picker
# 5. Each works in parallel via MCP tools (filesystem, git)
# 6. Aggregate all results into a single response
```

### Use Case 3: Live Patient Assistance (RUNTIME Mode)

**Scenario:** Help a patient reschedule their appointment via the AI assistant.

```bash
curl -X POST https://maos.your-domain.io/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: clinic-042" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "RUNTIME",
    "title": "Reschedule appointment",
    "description": "Patient wants to move their appointment from Monday to Wednesday",
    "payload": {
      "patient_id": "ref:patient-789",
      "appointment_id": "ref:appt-456",
      "requested_day": "Wednesday",
      "action": "reschedule"
    },
    "token_budget": 10000
  }'

# MAOS routes to Appointment_Assistant (RUNTIME, Backend)
# Agent uses domain API MCP tools to:
# 1. Check available Wednesday slots
# 2. Request Human_Approval (sensitive action — modifies live data)
# 3. After approval: cancel old appointment, book new one
# 4. Return confirmation
```

### Use Case 4: Debugging a Bug (DEVELOPMENT Mode)

```bash
curl -X POST https://maos.your-domain.io/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-Id: clinic-001" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "DEVELOPMENT",
    "title": "Debug mobile app crash on login",
    "description": "The Expo mobile app crashes with a null pointer when the user taps login on Android. Stack trace: NullPointerException at AuthScreen.tsx:42",
    "payload": {
      "target_system": "MOBILE",
      "stack_trace": "NullPointerException at AuthScreen.tsx:42",
      "platform": "android",
      "repro_steps": "1. Open app 2. Tap Login 3. App crashes"
    },
    "token_budget": 60000
  }'
```

---

## API Reference (All Endpoints)

### POST /v1/tasks — Submit a New Task

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mode` | `"DEVELOPMENT"` or `"RUNTIME"` | Yes | Operating mode |
| `title` | string | Yes | Short task title |
| `description` | string | Yes | Detailed description |
| `payload` | object | Yes | Task-specific data (target system, scope, etc.) |
| `token_budget` | integer | No | Max tokens (default: 100,000) |

**Headers:**
- `Authorization: Bearer <token>` — OAuth2 token (required)
- `X-Tenant-Id: <clinic-id>` — Your tenant/clinic identifier (required)
- `X-Auth-Scope: tasks:write` — RBAC scope (required)

**Responses:**
- `202 Accepted` — Task queued for processing
- `422 Unprocessable Entity` — Validation failed (field errors returned)
- `429 Too Many Requests` — System at capacity (`Retry-After` header included)
- `401 Unauthorized` — Missing or invalid auth token

### GET /v1/tasks/{task_id} — Check Task Status

**Responses:**
- `200 OK` — Returns task state and result (if completed)
- `404 Not Found` — Unknown task_id

**Response Body:**
```json
{
  "task_id": "01JFGK...",
  "state": "completed",       // assigned | in_progress | completed | failed | permanently_failed
  "result": {                  // present only when state is terminal
    "subtask_results": [...],
    "aggregated_status": "completed"
  }
}
```

### GET /healthz — Liveness Probe (no auth)

Returns `200 OK` if the service is alive. Used by Kubernetes liveness probes.

### GET /readyz — Readiness Probe (no auth)

Returns `200 OK` only if the service can accept and process tasks (Postgres + Redis reachable).

---

## Operating Modes Explained

### DEVELOPMENT Mode

| Aspect | Detail |
|--------|--------|
| **Purpose** | Code review, debugging, security analysis, feature implementation |
| **Data access** | Git repositories, filesystem (read-only by default) |
| **PHI exposure** | None — cannot access live patient data |
| **Tools available** | `filesystem_read`, `filesystem_write`, `git_log`, `git_diff`, `run_tests`, `lint_check` |
| **Agents** | Code_Reviewer, Debugger, Security_Subagent, Feature_Implementer (×3 platforms) |
| **Approval needed** | Only for write operations to production branches |

### RUNTIME Mode

| Aspect | Detail |
|--------|--------|
| **Purpose** | Live patient assistance, appointment management, billing |
| **Data access** | Domain APIs (appointment, billing, vitals) scoped to tenant |
| **PHI exposure** | Yes — BAA-compliant routing enforced (Bedrock/Vertex only) |
| **Tools available** | `appointment_query`, `appointment_book`, `billing_lookup`, `patient_vitals` |
| **Agents** | Appointment_Assistant, Billing_Assistant |
| **Approval needed** | All data-modifying operations (reschedule, cancel, charge) |

### Mode Separation is Structural

This is not a configuration flag. DEVELOPMENT and RUNTIME agents are given **different capability providers** at the code level:

- A DEVELOPMENT agent receives a `SourceArtifactProvider` — it can physically only call filesystem/git MCP tools
- A RUNTIME agent receives a `LiveDataProvider` — it can physically only call domain API MCP tools
- Cross-mode operations are **impossible** by construction, not by permission check

---

## Subagent Roster — Who Does What

### DEVELOPMENT Agents (12 total)

| Agent | Platform | Skills | Max Reasoning Steps | Max Tool Calls |
|-------|----------|--------|---------------------|---------------|
| Code_Reviewer (Backend) | BACKEND | `review-code`, `analyze-patterns` | 30 | 20 |
| Code_Reviewer (Web) | WEB | `review-code`, `analyze-patterns` | 30 | 20 |
| Code_Reviewer (Mobile) | MOBILE | `review-code`, `analyze-patterns` | 30 | 20 |
| Debugger (Backend) | BACKEND | `debug-runtime`, `trace-logs` | 40 | 30 |
| Debugger (Web) | WEB | `debug-runtime`, `trace-logs` | 40 | 30 |
| Debugger (Mobile) | MOBILE | `debug-runtime`, `trace-logs` | 40 | 30 |
| Security_Subagent (Backend) | BACKEND | `security-audit`, `vuln-scan` | 50 | 25 |
| Security_Subagent (Web) | WEB | `security-audit`, `vuln-scan` | 50 | 25 |
| Security_Subagent (Mobile) | MOBILE | `security-audit`, `vuln-scan` | 50 | 25 |
| Feature_Implementer (Backend) | BACKEND | `implement-feature`, `write-code` | 100 | 50 |
| Feature_Implementer (Web) | WEB | `implement-feature`, `write-code` | 100 | 50 |
| Feature_Implementer (Mobile) | MOBILE | `implement-feature`, `write-code` | 100 | 50 |

### RUNTIME Agents (2 total)

| Agent | Platform | Skills | Sensitive Actions |
|-------|----------|--------|-------------------|
| Appointment_Assistant | BACKEND | `appointment-query`, `appointment-modify` | Book, cancel, reschedule |
| Billing_Assistant | BACKEND | `billing-query`, `billing-charge` | Process payment, refund |

---

## How to Add Custom Agents

### Step 1: Define the Agent Specification

```python
from maos.contracts.agents import SubagentSpec, Skill, AgenticCapability
from maos.contracts.work_units import OperatingMode, PlatformSystem

new_agent = SubagentSpec(
    subagent_id="perf-analyzer-backend-001",
    role="Performance_Analyzer",
    platform_system=PlatformSystem.BACKEND,
    mode=OperatingMode.DEVELOPMENT,
    skills=[
        Skill(
            skill_id="analyze-performance",
            input_contract={"type": "object", "properties": {"scope": {"type": "array"}}},
            output_contract={"type": "object", "properties": {"bottlenecks": {"type": "array"}}},
            operation_scope=["read:source", "read:metrics", "run:profiler"],
        ),
    ],
    capability=AgenticCapability(
        max_reasoning_steps=60,
        max_tool_invocations=30,
    ),
    mcp_allow_list=["filesystem_read", "git_log", "run_profiler", "query_metrics"],
    selection_priority=5,
)
```

### Step 2: Register via the Agent Registry

```python
from maos.registry import AgentRegistry

# Get a database pool (from your app context)
registry = AgentRegistry(pool)

# Register — the agent is immediately routable
await registry.register(new_agent)
```

### Step 3: That's It

No orchestrator code changes needed. The next time a task requires `analyze-performance` skill on BACKEND in DEVELOPMENT mode, your new agent will be selected automatically.

### Step 4: Remove When Needed

```python
await registry.remove("perf-analyzer-backend-001")
# Agent immediately stops receiving new work
# In-progress work completes normally
```

---

## How to Add Custom MCP Tools

### Step 1: Define the Tool Descriptor

```python
from maos.contracts.mcp import MCPToolDescriptor
from maos.contracts.work_units import OperatingMode

new_tool = MCPToolDescriptor(
    name="run_profiler",
    server="profiler-mcp-server",
    input_contract={
        "type": "object",
        "properties": {
            "target_file": {"type": "string"},
            "duration_seconds": {"type": "integer", "maximum": 30}
        },
        "required": ["target_file"]
    },
    output_contract={
        "type": "object",
        "properties": {
            "hotspots": {"type": "array"},
            "total_time_ms": {"type": "number"}
        }
    },
    allowed_modes=[OperatingMode.DEVELOPMENT],  # DEVELOPMENT only
)
```

### Step 2: Add to Agent's Allow List

Include `"run_profiler"` in the agent's `mcp_allow_list` when registering.

### Step 3: Deploy the MCP Server

Deploy your `profiler-mcp-server` as a pod in the `maos` namespace with the label `app.kubernetes.io/component: mcp-server`.

---

## Security Model — Deep Dive

### Layer 1: Authentication and Authorization

- Every API call requires an OAuth2 Bearer token
- Tokens are validated against the configured JWKS endpoint
- Each token carries `tenant_id` and `auth_scope` claims
- RBAC checks ensure the requester can perform the requested operation

### Layer 2: Multi-Tenant Isolation

- Every Task is tagged with `tenant_id` at intake (from the auth token)
- `tenant_id` propagates to every Subtask, SubSubtask, and Shared_Context entry
- Data access is filtered by `tenant_id` at every persistence layer query
- Cross-tenant access is denied and audited (not just logged — a permanent audit record)

### Layer 3: Operating Mode Separation

- DEVELOPMENT agents receive `SourceArtifactProvider` → can only access repos
- RUNTIME agents receive `LiveDataProvider` → can only access domain APIs
- Mode is enforced at the capability provider level, not by permission check
- A DEVELOPMENT agent cannot even reference a RUNTIME tool's existence

### Layer 4: MCP Tool Governance

- Each agent has an explicit `mcp_allow_list` — only those tools are callable
- Each tool declares `allowed_modes` — tool won't execute in the wrong mode
- Arguments are validated against the tool's JSON Schema before invocation
- Code-executing tools route through the gVisor sandbox (no network, capped resources)

### Layer 5: PHI Protection

- RUNTIME mode LLM calls route only through BAA-covered providers (Bedrock/Vertex)
- PHI is referenced by ID in messages — never raw values
- Audit entries, telemetry, and error reports are scrubbed before persistence/transmission
- Prompt/semantic caches skip PHI requests entirely (never cached)
- Sentry `before_send` hook strips any PHI patterns from error events

### Layer 6: Human-in-the-Loop Approval

- Sensitive actions (data modifications in RUNTIME mode) require explicit human approval
- Implemented as a LangGraph interrupt — execution pauses until approved
- Approval has a configurable timeout window — expiry = denial
- Both approvals and denials are audited

### Layer 7: Audit Trail

- Append-only `audit_log` table (DB grants prevent UPDATE/DELETE)
- Every routing decision, tool invocation, error, and state transition is recorded
- Entries include all applicable IDs (task, subtask, sub_subtask, agent)
- All audit content is redacted of PHI/secrets before persistence

---

## Observability — Monitoring Your Agents

### Structured Logs (stdout, JSON)

Every log entry includes automatic correlation:

```json
{
  "event": "agent.reasoning_step",
  "agent_id": "code-reviewer-backend-001",
  "task_id": "01JFGK...",
  "tenant_id": "clinic-001",
  "trace_id": "abc123def456...",
  "span_id": "7890abcd",
  "step_index": 3,
  "timestamp": "2026-06-27T10:30:15.123Z",
  "level": "info"
}
```

### Metrics (Prometheus / Grafana)

| Metric | Type | Description |
|--------|------|-------------|
| `maos.tasks.submitted` | Counter | Total tasks received |
| `maos.tasks.completed` | Counter | Successfully completed tasks |
| `maos.tasks.failed` | Counter | Permanently failed tasks |
| `maos.model_calls.total` | Counter | Total LLM invocations |
| `maos.model_calls.duration` | Histogram | LLM call latency (seconds) |
| `maos.mcp_invocations.total` | Counter | Total tool invocations |
| `maos.routing_decisions.total` | Counter | Agent selection decisions |

### Distributed Tracing (Jaeger / Tempo)

Full OpenTelemetry traces spanning:
```
API request → Root Orchestrator → Sub-Orchestrator → Subagent → LLM call → MCP tool → Response
```

### Agent-Level Tracing (LangSmith / Langfuse)

When configured, every agent execution is traced with:
- Individual reasoning steps
- Tool calls with duration
- Model calls with token counts
- Error events

### Error Reporting (Sentry)

- Unhandled exceptions captured automatically (FastAPI + Arq)
- Task context attached (task_id, tenant_id, trace_id)
- PHI/secrets stripped via `before_send` hook
- Grouped by exception type + stack trace

---

## Cost Controls and Budgets

### Per-Task Token Budget

Every task has a `token_budget` (default 100,000 tokens). When the budget is reached:
1. All further LLM calls are blocked
2. The task returns a `budget_exceeded` result
3. Partial results from completed sub-tasks are still returned

### Per-Tenant Daily Ceiling

Each tenant has a daily ceiling (default 5,000,000 tokens). This prevents any single tenant from monopolizing resources.

### Per-Agent Capability Budgets

Each agent declares bounded capabilities:
- `max_reasoning_steps`: Maximum iterations in the reasoning loop
- `max_tool_invocations`: Maximum MCP tool calls per execution

When either is hit, the agent stops and returns what it has.

### Prompt + Semantic Cache (Dragonfly)

Two cache layers reduce redundant LLM calls:
1. **Prompt Cache**: Exact hash match — identical requests return cached responses (1hr TTL)
2. **Semantic Cache**: Embedding similarity — paraphrased requests match (0.95 cosine threshold)

PHI requests are NEVER cached.

### Cost Tracking

The `Cost_Meter` records every LLM call:
- Provider + model used
- Tokens consumed
- Estimated USD cost
- Queryable per agent, per task, and per tenant

---

## Resilience and Fault Tolerance

### Circuit Breakers

| Dependency | Failure Threshold | Recovery Timeout | Half-Open Probes |
|-----------|-------------------|-----------------|-----------------|
| LLM Provider | 3 failures | 60s | 1 |
| Postgres | 5 failures | 30s | 2 |
| Redis | 5 failures | 15s | 2 |
| MCP Server | 3 failures | 45s | 1 |

When a circuit opens, calls to that dependency are instantly rejected (fail-fast) instead of timing out.

### Retry with Backoff

All external calls use exponential backoff with full jitter:
- Base delay: 0.25–1.0s depending on dependency
- Max delay: 2–30s depending on dependency
- Max attempts: 2–3 depending on dependency

### Timeout per Call

Every external call has a wall-clock deadline. On timeout:
1. The work unit is marked `timed_out`
2. It counts as a failed attempt
3. Reassignment to an alternative agent is attempted

### Context Handoff (LLM Provider Fallback)

When an LLM provider hits rate/quota/context-window limits:
1. The system detects the limit condition
2. Selects the next residency-permitted provider from the fallback chain
3. Transfers full conversation context + working memory
4. Continues execution from the interruption point
5. If all providers exhausted → graceful failure with state persisted for later resume

### Backpressure (429 + Retry-After)

When the system is overloaded:
- Queue depth exceeds threshold → new tasks get `429 Too Many Requests`
- Global concurrency cap reached → `429`
- Per-tenant cap reached → `429` (only for that tenant)
- The `Retry-After` header tells clients when to retry (default 30s)

---

## Configuration Reference

### All Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAOS_POSTGRES_DSN` | `postgresql://maos:maos@localhost:5432/maos` | Postgres connection string |
| `MAOS_REDIS_URL` | `redis://localhost:6379/0` | Redis for Shared_Context |
| `MAOS_BROKER_URL` | `redis://localhost:6379/1` | Redis for Arq task broker |
| `MAOS_DRAGONFLY_CACHE_URL` | `redis://localhost:6379/2` | Dragonfly for LLM caches |
| `MAOS_PROMPT_CACHE_TTL` | `3600` | Prompt cache TTL in seconds |
| `MAOS_SEMANTIC_CACHE_THRESHOLD` | `0.95` | Cosine similarity for semantic cache hits |
| `MAOS_DEFAULT_TASK_TOKEN_BUDGET` | `100000` | Default per-task token budget |
| `MAOS_TENANT_DAILY_TOKEN_CEILING` | `5000000` | Daily token ceiling per tenant |
| `MAOS_GLOBAL_CONCURRENCY_CAP` | `100` | Max simultaneous tasks globally |
| `MAOS_TENANT_CONCURRENCY_CAP` | `10` | Max simultaneous tasks per tenant |
| `MAOS_MAX_QUEUE_DEPTH` | `200` | Max pending jobs before backpressure |
| `MAOS_BACKPRESSURE_RETRY_AFTER` | `30` | Retry-After seconds in 429 responses |
| `ANTHROPIC_API_KEY` | — | Anthropic Claude API key |
| `OPENAI_API_KEY` | — | OpenAI fallback API key |
| `GOOGLE_API_KEY` | — | Google Vertex API key |
| `AWS_REGION` | — | AWS region for Bedrock |
| `SECRETS_BACKEND` | `env` | `env`, `vault`, or `aws` |
| `VAULT_ADDR` | `http://127.0.0.1:8200` | Vault server URL |
| `VAULT_TOKEN` | — | Vault auth token |
| `SENTRY_DSN` | — | Sentry DSN for error reporting |
| `LANGSMITH_API_KEY` | — | LangSmith agent tracing |
| `LANGFUSE_HOST` | — | Langfuse host (alternative to LangSmith) |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | — | Langfuse secret key |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTel collector gRPC endpoint |
| `MAOS_LOG_LEVEL` | `INFO` | Minimum log level |
| `MAOS_JSON_LOGS` | `true` | JSON log format (false = console) |
| `MAOS_ENVIRONMENT` | `development` | deployment environment name |

---

## Project Structure

```
maos/
├── src/maos/
│   ├── api/             # FastAPI routes, auth middleware, rate limiting
│   ├── audit/           # Audit entry builders (append-only, redacted)
│   ├── config/          # Settings (pydantic-settings) + secrets providers
│   ├── contracts/       # Pydantic v2 domain models (all data shapes)
│   ├── core/            # Pure orchestration logic (zero I/O, fully testable)
│   ├── cost/            # Cost_Meter for token/cost tracking
│   ├── graphs/          # LangGraph supervisor graphs + agent roster
│   ├── llm/             # LLM adapter, residency policy, Dragonfly cache
│   ├── mcp/             # MCP Gateway, governance checks, sandbox runner
│   ├── memory/          # Postgres pool, Shared_Context, Semantic_Memory, sweepers
│   ├── messaging/       # Agent_Message bus (Redis Streams) + codec
│   ├── migrations/      # SQL schemas + migration runner
│   ├── observability/   # Logging, tracing, metrics, Sentry, agent tracing
│   ├── registry/        # Agent_Registry (Postgres-backed)
│   ├── resilience/      # Circuit breakers, retry, timeout, composed policies
│   ├── security/        # Tenant isolation, RBAC, mode separation, redaction
│   └── workers/         # Arq workers, backpressure, concurrency limiter
├── tests/
│   ├── property/        # Hypothesis property-based tests (57 properties)
│   ├── unit/            # Unit tests
│   └── integration/     # Integration tests
├── k8s/                 # Kubernetes manifests (12 files)
├── Dockerfile.api       # API container image
├── Dockerfile.worker    # Worker container image
├── Dockerfile.sandbox   # Sandbox container image
├── .dockerignore
├── pyproject.toml       # Dependencies, tooling config
└── README.md            # This file
```

---

## Troubleshooting

### "429 Too Many Requests" on Task Submission

**Cause:** System is at capacity (queue too deep or concurrency cap reached).

**Fix:**
1. Check queue depth: `redis-cli ZCARD arq:queue`
2. Check active jobs: `redis-cli GET maos:concurrency:global`
3. If genuinely overloaded: scale up workers (`kubectl scale deployment maos-worker --replicas=5 -n maos`)
4. If misconfigured: increase `MAOS_GLOBAL_CONCURRENCY_CAP` or `MAOS_MAX_QUEUE_DEPTH`

### Task Stuck in "in_progress"

**Cause:** Worker crashed mid-execution.

**Fix:** Another worker will automatically resume from the latest checkpoint. If no workers are running:
1. Check worker logs: `kubectl logs -l app.kubernetes.io/name=maos-worker -n maos`
2. Restart workers: `kubectl rollout restart deployment maos-worker -n maos`

### "Circuit breaker OPEN" Errors

**Cause:** An external dependency (LLM, Postgres, Redis) has failed repeatedly.

**Fix:**
1. Check the failing dependency's health
2. The circuit will auto-recover after the `recovery_timeout` (15–60s depending on dependency)
3. For manual reset: restart the worker pod

### LLM Calls Failing with "No Permitted Provider"

**Cause:** All providers in the fallback chain are unhealthy or the residency policy excludes all available ones.

**Fix:**
1. Check API keys are valid: `echo $ANTHROPIC_API_KEY | head -c 10`
2. For PHI calls: ensure Bedrock or Vertex credentials are configured
3. Check provider health: circuit breaker state in logs

### Migrations Fail

**Cause:** Postgres not reachable or migration SQL has errors.

**Fix:**
1. Verify Postgres is running: `pg_isready -h localhost -p 5432`
2. Check migration logs: `kubectl logs job/maos-db-migration -n maos`
3. Manually fix and re-run: `kubectl delete job maos-db-migration -n maos && kubectl apply -f k8s/migration-job.yaml`

---

## FAQ

**Q: Can I use MAOS without Kubernetes?**
A: Yes. For local development, just run the API server and Arq worker directly (Steps 8-9 in local setup). Docker Compose is also an option for staging.

**Q: How do I add a new platform system (e.g., a new microservice)?**
A: Register a new Sub-Orchestrator through the Agent_Registry with the new `platform_system` value. No orchestrator code changes needed.

**Q: What happens if an agent runs out of budget?**
A: The agent stops immediately, returns partial results, and the task is marked with the appropriate status. Partial results from completed sub-tasks are still available.

**Q: Can agents talk to each other?**
A: Yes, via Peer Delegation. An agent can request delegation to another agent's skill through the Sub-Orchestrator, subject to the same routing rules + depth cap.

**Q: Is data encrypted at rest?**
A: Postgres encryption-at-rest should be configured at the infrastructure level (RDS encryption, Kubernetes PV encryption). pgvector entries are encrypted alongside the database. Redis/Dragonfly should use encrypted volumes.

**Q: How fast does it scale?**
A: API pods scale within 60s (HPA, CPU-triggered). Workers scale within 30s (KEDA, queue-lag-triggered). From 2 → 20 worker pods under load.

**Q: What if Anthropic is down?**
A: The LLM adapter automatically falls back through the provider chain: Anthropic → OpenAI → Bedrock → Vertex. If all are down, the circuit breaker opens and tasks fail gracefully with state preserved for later resume.

**Q: Can I run the optional property tests?**
A: Yes. They are Hypothesis-based and live in `tests/property/`. Run with `uv run pytest tests/property/ -v`.

---

## License

Proprietary — Healthcare Platform Team


---

## Implementation Deep Dive — Core Modules

This section explains the internal architecture with actual code from the implementation.
Understanding these modules will help you extend, debug, and maintain MAOS.

### Pure Orchestration Core — Design Philosophy

The `src/maos/core/` package contains **pure, side-effect-free functions** that implement
all orchestration logic. "Pure" means:

- No database calls, no network I/O, no file access
- Output depends only on inputs (deterministic)
- Every function is directly testable with Hypothesis property tests
- The LangGraph nodes wrap these pure functions with I/O

This separation means you can unit-test ALL orchestration logic without Docker, databases,
or external services.

### Work-Unit State Machine (`core/state_machine.py`)

Every Subtask and SubSubtask follows a strict lifecycle. The state machine is defined
as an immutable transition table:

```python
# Legal transitions — immutable at runtime
LEGAL_TRANSITIONS = {
    WorkUnitState.ASSIGNED: frozenset({
        WorkUnitState.IN_PROGRESS,        # subagent starts
        WorkUnitState.AWAITING_APPROVAL,  # sensitive action gate
    }),
    WorkUnitState.AWAITING_APPROVAL: frozenset({
        WorkUnitState.IN_PROGRESS,  # approval granted
        WorkUnitState.FAILED,       # approval denied / window elapsed
    }),
    WorkUnitState.IN_PROGRESS: frozenset({
        WorkUnitState.COMPLETED,    # result conforms to output contract
        WorkUnitState.FAILED,       # error
        WorkUnitState.TIMED_OUT,    # no response within timeout
    }),
    WorkUnitState.TIMED_OUT: frozenset({WorkUnitState.FAILED}),
    WorkUnitState.FAILED: frozenset({
        WorkUnitState.ASSIGNED,           # reassigned (alt agent, attempts left)
        WorkUnitState.PERMANENTLY_FAILED, # max attempts reached
    }),
    WorkUnitState.COMPLETED: frozenset(),           # terminal
    WorkUnitState.PERMANENTLY_FAILED: frozenset(),  # terminal
}
```

**Usage — Event-Driven Transitions:**

```python
from maos.core.state_machine import apply_event, IllegalTransitionError
from maos.contracts.work_units import WorkUnitState

# Agent starts working
next_state = apply_event(WorkUnitState.ASSIGNED, "subagent_starts")
# → WorkUnitState.IN_PROGRESS

# Agent finishes successfully
next_state = apply_event(WorkUnitState.IN_PROGRESS, "result_conforms")
# → WorkUnitState.COMPLETED

# Invalid transition raises an error
try:
    apply_event(WorkUnitState.COMPLETED, "error")  # terminal state!
except IllegalTransitionError as e:
    print(e)  # "illegal work-unit transition: no rule for (completed, 'error')"
```

**Usage — Timeout Handling:**

```python
from maos.core.state_machine import handle_timeout

# SubSubtask timed out — count as failed attempt
updated_unit, next_state = handle_timeout(sub_subtask, max_attempts=3)
# If attempts < 3: next_state = FAILED (allows reassignment)
# If attempts >= 3: next_state = PERMANENTLY_FAILED
```


### Budget Accounting (`core/budget.py`)

Agents have bounded capabilities — they cannot run forever. Two budget types:

**1. Reasoning Steps + Tool Invocations (per agent execution):**

```python
from maos.core.budget import BudgetTracker, record_reasoning_step, record_tool_invocation
from maos.contracts.agents import AgenticCapability

# Agent declares: max 30 reasoning steps, 20 tool calls
cap = AgenticCapability(max_reasoning_steps=30, max_tool_invocations=20)
tracker = BudgetTracker(capability=cap)

# During execution — each step is tracked
tracker = record_reasoning_step(tracker)   # step 1
tracker = record_reasoning_step(tracker)   # step 2
tracker = record_tool_invocation(tracker)  # tool 1

# When budget exhausted:
# BudgetExceededError("Budget exceeded: reasoning_steps reached 31/30")
```

**2. Token Budget (per task, across all agents):**

```python
from maos.core.budget import check_token_budget, TokenBudgetExceededError

# Before each LLM call, the Cost_Meter checks:
check_token_budget(
    cumulative_tokens=95000,  # tokens used so far
    budget=100000,            # task's token budget
    task_id="01JFGK..."
)
# Returns None → proceed with LLM call

# When budget exceeded:
check_token_budget(cumulative_tokens=100500, budget=100000, task_id="01JFGK...")
# Raises: TokenBudgetExceededError("Token budget exceeded for task 01JFGK...: 100500/100000")
```

### Task Decomposition (`core/decomposition.py`)

The decomposition engine classifies a high-level Task and breaks it into platform-specific
Subtasks, then further into SubSubtasks assignable to individual agents:

```python
from maos.core.decomposition import (
    decompose_task_to_subtasks,
    decompose_subtask_to_sub_subtasks,
    compute_routing_target,
)

# Level 1: Task → Subtasks (one per platform involved)
subtasks = decompose_task_to_subtasks(task)
# Returns: [Subtask(platform=BACKEND, ...), Subtask(platform=MOBILE, ...)]

# Each subtask targets exactly one platform
for subtask in subtasks:
    assert subtask.platform_system in ("BACKEND", "WEB", "MOBILE")
    assert subtask.mode == task.mode       # mode propagated
    assert subtask.tenant_id == task.tenant_id  # tenant propagated

# Routing: which Sub-Orchestrator handles this Subtask?
target = compute_routing_target(subtask)
# → "sub_orchestrator_backend"

# Level 2: Subtask → SubSubtasks (one per skill needed)
sub_subtasks = decompose_subtask_to_sub_subtasks(subtask)
# Each has a required_skill for agent selection
```

### Deterministic Agent Selection (`core/selection.py`)

Agent selection is a **pure, total function** of the registry snapshot:

```python
from maos.core.selection import select_subagent

# Given candidate agents from the registry:
selected = select_subagent(
    candidates=registry_snapshot,
    platform_system=PlatformSystem.BACKEND,
    skill_id="security-audit",
    mode=OperatingMode.DEVELOPMENT,
)

# Selection rules (in order):
# 1. Filter: platform_system matches
# 2. Filter: has a Skill with matching skill_id
# 3. Filter: mode matches
# 4. Filter: status == "available"
# 5. Sort by: highest selection_priority
# 6. Tie-break: lexicographically smallest subagent_id
#
# Result is ALWAYS the same given the same inputs (deterministic).
# Returns None when no candidate matches.
```

### Result Aggregation (`core/aggregation.py`)

Results flow upward through the hierarchy:

```python
from maos.core.aggregation import aggregate_subtask, aggregate_task

# SubSubtask results → Subtask result
subtask_result = aggregate_subtask(sub_subtask_results)
# Includes: every unit's status, IDs, and any permanently_failed units

# Subtask results → Task result
task_result = aggregate_task(subtask_results)
# Final aggregated result returned to the requester
# Contains per-platform breakdown with all unit statuses
```

---

## Implementation Deep Dive — Infrastructure Layer

### Database Pool and Persistence (`memory/database.py`)

MAOS uses psycopg (async) with PgBouncer-compatible pooling:

```python
from maos.memory.database import create_pool, DatabasePool
from maos.config.settings import get_settings

# Create pool (called once at startup)
settings = get_settings()
pool: DatabasePool = create_pool(settings.postgres)
await pool.open()

# Use throughout the application
async with pool.acquire() as conn:
    result = await conn.execute("SELECT * FROM task WHERE task_id = %s", (task_id,))
    row = await result.fetchone()

# Clean shutdown
await pool.close()
```

### Agent Registry (`registry/`)

The registry is the source of truth for agent routing:

```python
from maos.registry import AgentRegistry

registry = AgentRegistry(pool)

# Register a new agent (immediately routable)
await registry.register(agent_spec)

# Find agents for a platform
agents = await registry.available_agents(PlatformSystem.BACKEND)

# Select the best agent for a task
best = await registry.select(
    platform=PlatformSystem.BACKEND,
    skill_id="debug-runtime",
    mode=OperatingMode.DEVELOPMENT,
)

# Remove an agent (stops receiving new work)
await registry.remove("agent-id-to-remove")
```

### Shared Context (`memory/shared_context.py`)

Redis-backed per-Task context that agents share during execution:

```python
from maos.memory.shared_context import SharedContext

ctx = SharedContext(redis_client)

# Create context when Task is accepted
await ctx.create(task_id="01JFGK...", assigned_agents=["agent-1", "agent-2"])

# Agents write findings/state (attributed with agent_id + timestamp)
await ctx.write(
    task_id="01JFGK...",
    agent_id="agent-1",
    key="security_findings",
    value={"vulnerabilities": [...], "severity": "high"},
)

# Other assigned agents can read
data = await ctx.read(task_id="01JFGK...", agent_id="agent-2", key="security_findings")

# Non-assigned agents are DENIED (and the denial is audited)
# await ctx.read(task_id="01JFGK...", agent_id="rogue-agent", key="...")
# → AccessDeniedError + audit entry

# Terminal state closes context to further writes
await ctx.close_for_writes(task_id="01JFGK...")
```


### LLM Provider Adapter (`llm/adapter.py`)

The sole entry point for ALL model calls — no agent logic imports provider SDKs directly:

```python
from maos.llm.adapter import LLMProviderAdapter
from maos.contracts.llm import LLMRequest, LLMResponse

adapter = LLMProviderAdapter(
    residency_policy=residency_policy,
    cost_meter=cost_meter,
    fallback_chain=["anthropic", "openai", "bedrock", "vertex"],
)

# Make a model call
request = LLMRequest(
    messages=[
        {"role": "system", "content": "You are a security analyst."},
        {"role": "user", "content": "Review this code for SQL injection..."},
    ],
    model_hint="claude-sonnet-4-20250514",
    contains_phi=False,
    tenant_id="clinic-001",
)

response: LLMResponse = await adapter.complete(request)
# response.content, response.tokens_used, response.provider, response.model
```

**What happens internally:**
1. Check prompt cache (Dragonfly) → return cached if hit
2. Check semantic cache → return if similar request found
3. Route through residency policy (PHI → BAA providers only)
4. Call provider with timeout + retry
5. On provider failure → fallback to next in chain
6. Record tokens to Cost_Meter
7. Store in both caches for future hits
8. Return response

### Dragonfly Cache (`llm/cache.py`)

Two-layer caching that avoids redundant LLM calls:

```python
from maos.llm.cache import CachedLLMAdapter, PromptCache, SemanticCache, CacheConfig
import redis.asyncio as aioredis

# Configure
config = CacheConfig(
    dragonfly_url="redis://dragonfly:6379/2",
    prompt_cache_ttl_seconds=3600,      # 1 hour
    semantic_cache_threshold=0.95,       # 95% similarity
)

# Create cache layers
client = aioredis.from_url(config.dragonfly_url)
prompt_cache = PromptCache(client, config)
semantic_cache = SemanticCache(client, config, embedding_provider)

# Wrap the adapter
cached_adapter = CachedLLMAdapter(
    prompt_cache=prompt_cache,
    semantic_cache=semantic_cache,
    provider_adapter=raw_adapter,
)

# Now calls check: prompt_cache → semantic_cache → provider → store back
response = await cached_adapter.complete(request)

# PHI requests ALWAYS bypass cache (never stored, never returned)
phi_request = LLMRequest(..., contains_phi=True)
# → goes directly to provider, no caching
```

### MCP Gateway and Governance (`mcp/gateway.py`, `mcp/governance.py`)

Tool invocations are governed by strict allow-lists:

```python
from maos.mcp.governance import check_tool_permission, ToolDenialReason

# Before any tool invocation:
denial = check_tool_permission(
    agent=agent_spec,
    tool_name="filesystem_write",
    tool_descriptor=tool_descriptor,
    args={"path": "/src/auth/login.ts", "content": "..."},
)

if denial is not None:
    # Tool invocation BLOCKED
    # denial.reason: "not_in_allow_list" | "mode_not_permitted" | "invalid_args"
    # → audit entry recorded, agent informed
    pass
else:
    # Tool invocation PERMITTED → execute via gateway
    result = await gateway.invoke(agent, invocation, args)
    # If code-executing → routed through gVisor sandbox
```

**Governance rules (checked in order):**
1. Is the tool in the agent's `mcp_allow_list`? → No = deny + audit
2. Does the tool's `allowed_modes` include the agent's mode? → No = deny + audit
3. Do the args validate against the tool's `input_contract` (JSON Schema)? → No = deny + audit
4. Is the tool code-executing? → Yes = route through sandbox

### Sandbox Runner (`mcp/sandbox.py`)

Code-executing tools run in gVisor isolation:

```python
from maos.mcp.sandbox import Sandbox, ExecutionScope, SandboxResult

sandbox = Sandbox()

result: SandboxResult = await sandbox.run(
    code="import os; print(os.listdir('.'))",
    scope=ExecutionScope(
        readable_paths=["/workspace/src/"],
        writable_paths=[],  # read-only by default
    ),
    cpu="500m",
    mem="256Mi",
    network="none",       # NO network access
    timeout_s=30,
)

# result.stdout, result.stderr, result.exit_code
# If the code tries to access /etc/passwd → DENIED
# If the code tries network access → DENIED
# If it exceeds timeout → killed + timed_out
```

### Resilience Policies (`resilience/policies.py`)

Every external dependency is protected by composed resilience:

```python
from maos.resilience import resilient_call, DependencyType

# Make a resilient call to an LLM provider:
response = await resilient_call(
    provider.call_model,          # the async function to protect
    request,                       # arguments
    dependency_name="anthropic_claude",
    dependency_type=DependencyType.LLM_PROVIDER,
    on_timeout=mark_unit_timed_out,  # callback if timeout fires
)

# What happens internally:
# 1. Circuit breaker check → if OPEN, instant CircuitBreakerError
# 2. Retry loop (up to 3 attempts for LLM):
#    a. Start wall-clock timeout (60s for LLM)
#    b. Execute the function
#    c. On success → reset circuit breaker → return result
#    d. On failure → increment circuit failure count → backoff → retry
#    e. On timeout → on_timeout callback → count as failure → retry
# 3. If all retries exhausted → RetryExhaustedError
```

**Pre-configured policies per dependency:**

```python
# LLM: 3 failures opens circuit, 60s recovery, 60s timeout, 3 retries
# Postgres: 5 failures opens, 30s recovery, 10s timeout, 3 retries
# Redis: 5 failures opens, 15s recovery, 5s timeout, 3 retries
# MCP Server: 3 failures opens, 45s recovery, 30s timeout, 2 retries
```

---

## Implementation Deep Dive — LangGraph Orchestration

### Root Orchestrator Graph (`graphs/root_orchestrator.py`)

The top-level LangGraph supervisor graph:

```python
# Simplified structure of the Root Orchestrator graph:

async def run_root_orchestrator(task_id, tenant_id, resume_state, db_pool):
    """Execute the Root Orchestrator graph for a Task."""

    # Node 1: Intake — validate and classify the Task
    # Node 2: Decompose — break into Subtasks per platform
    # Node 3: Route — send each Subtask to its Sub-Orchestrator
    # Node 4: Monitor — track status of all Subtasks
    # Node 5: Aggregate — combine results when all complete/fail

    # Every node transition is checkpointed to Postgres
    # If this worker dies, another resumes from the latest checkpoint
```

### Sub-Orchestrator Graph (`graphs/sub_orchestrator.py`)

Platform-specific orchestration:

```python
async def run_sub_orchestrator(subtask_id, task_id, tenant_id, platform_system, ...):
    """Execute the Sub-Orchestrator graph for a Subtask."""

    # Node 1: Decompose Subtask into SubSubtasks
    # Node 2: For each SubSubtask:
    #   a. Select best agent via registry (deterministic)
    #   b. Record routing decision to audit
    #   c. Assign to agent → state = ASSIGNED
    # Node 3: Monitor agent execution
    #   - Track state transitions
    #   - Handle timeouts (mark timed_out, count attempt)
    #   - Handle failures (reassign if attempts remain)
    # Node 4: Aggregate SubSubtask results → SubtaskResult
```

### Subagent Runtime (`graphs/subagent_runtime.py`)

The bounded reasoning loop each agent runs:

```python
async def run_subagent(sub_subtask, agent_spec, context):
    """Execute a Subagent's bounded reasoning loop."""

    budget_tracker = BudgetTracker(capability=agent_spec.capability)

    for step in range(agent_spec.capability.max_reasoning_steps):
        # 1. Record reasoning step (budget check)
        budget_tracker = record_reasoning_step(budget_tracker)

        # 2. Ask LLM what to do next (via adapter — never direct SDK)
        response = await adapter.complete(reasoning_prompt)

        # 3. If LLM says "invoke tool X":
        if response.wants_tool_call:
            # Budget check
            budget_tracker = record_tool_invocation(budget_tracker)
            # Governance check (allow-list, mode, args)
            # Execute via MCP Gateway (sandbox if code-executing)
            tool_result = await gateway.invoke(agent_spec, tool_call, args)

        # 4. If LLM says "I'm done, here's my result":
        if response.is_final:
            # Validate output against Skill's output_contract
            validate_output_contract(response.result, skill.output_contract)
            return response.result

        # 5. If sensitive action detected:
        if response.is_sensitive:
            # Trigger Human_Approval interrupt (LangGraph)
            approval = await human_approval.request(sub_subtask.sub_subtask_id)
            if not approval.granted:
                raise ApprovalDeniedError(...)

    # Budget exhausted — return partial result
    return BudgetExceededResult(...)
```


### Peer Delegation (`graphs/delegation.py`)

When an agent finds part of its work matches another agent's skill:

```python
from maos.graphs.delegation import DelegationRouter
from maos.contracts.work_units import OperatingMode, PlatformSystem

router = DelegationRouter(
    registry=registry,
    audit=audit_log,
    max_delegation_depth=3,  # prevent unbounded chains
)

# Agent requests delegation
result = await router.route(DelegationRequest(
    delegation_id="del-001",
    origin_sub_subtask_id="sst-042",
    subtask_id="st-007",
    task_id="01JFGK...",
    delegating_subagent_id="feature-impl-backend-001",
    tenant_id="clinic-001",
    mode=OperatingMode.DEVELOPMENT,
    platform_system=PlatformSystem.BACKEND,
    required_skill="security-audit",      # needs Security agent
    input_contract={...},
    depth=1,                              # current delegation depth
))

# Possible outcomes:
# 1. DelegatedWork — peer accepted, work is traceable + audited
# 2. PeerRejection — no peer available, treated as failed attempt
# 3. Denied — depth would exceed max (audited as "delegation_denied")
```

---

## Implementation Deep Dive — Workers and Scaling

### Arq Workers (`workers/`)

Workers are stateless — they pull tasks from Redis and resume from Postgres checkpoints:

```python
# Start a worker (from CLI):
# arq maos.workers.orchestration.OrchestrationWorkerSettings

# Worker lifecycle:
# 1. on_startup: open DB pool, store in context
# 2. Poll Redis broker queue for jobs
# 3. For each job: process_task(ctx, task_id)
#    a. Load Task from DB
#    b. Acquire concurrency slot (global + per-tenant)
#    c. Load latest checkpoint (if resuming)
#    d. Run Root Orchestrator LangGraph graph
#    e. Release concurrency slot
# 4. on_shutdown: close DB pool

# Configuration:
# - max_jobs: 10 per worker (local cap)
# - job_timeout: 600s (10 min for long orchestration)
# - queue_read_limit: 50 jobs per poll cycle
```

### Concurrency Limiter (`workers/concurrency.py`)

Distributed concurrency caps using Redis atomic counters:

```python
from maos.workers.concurrency import ConcurrencyLimiter

limiter = ConcurrencyLimiter(redis_url="redis://localhost:6379/1")

# Before processing a task:
acquired = await limiter.acquire(tenant_id="clinic-001")
if not acquired:
    # Over capacity — task will be retried by Arq later
    return {"retry": True}

try:
    # ... do work ...
    pass
finally:
    # ALWAYS release in finally block
    await limiter.release(tenant_id="clinic-001")

# Two caps enforced:
# - Global: max 100 tasks across all tenants (MAOS_GLOBAL_CONCURRENCY_CAP)
# - Per-tenant: max 10 tasks per tenant (MAOS_TENANT_CONCURRENCY_CAP)
# Uses Redis INCR/DECR with TTL safety keys to prevent leaked slots
```

### Backpressure Guard (`workers/backpressure.py`)

Prevents unbounded queue growth at the API layer:

```python
from maos.workers.backpressure import BackpressureGuard, BackpressureError

guard = BackpressureGuard.from_settings()

# In the POST /v1/tasks endpoint:
try:
    await guard.check_or_raise(tenant_id=ctx.tenant_id)
except BackpressureError as exc:
    # Return 429 Too Many Requests
    raise HTTPException(
        status_code=429,
        detail=exc.detail,
        headers={"Retry-After": str(exc.retry_after)},
    )

# Three checks performed:
# 1. Queue depth: pending jobs in Arq sorted set < MAOS_MAX_QUEUE_DEPTH (200)
# 2. Global active: running tasks < MAOS_GLOBAL_CONCURRENCY_CAP (100)
# 3. Per-tenant active: tenant's tasks < MAOS_TENANT_CONCURRENCY_CAP (10)
```

---

## Implementation Deep Dive — Security

### Tenant Isolation Guard (`security/tenant_guard.py`)

Every data access is filtered by tenant:

```python
from maos.security.tenant_guard import enforce_tenant_isolation

# Before any data access:
enforce_tenant_isolation(
    requesting_tenant="clinic-001",
    resource_tenant="clinic-001",  # must match!
)
# → passes silently

enforce_tenant_isolation(
    requesting_tenant="clinic-001",
    resource_tenant="clinic-002",  # MISMATCH
)
# → raises TenantIsolationError + audit entry recorded
```

### Mode Separation (`security/capability_providers.py`)

Agents receive different capability providers based on their mode:

```python
from maos.security.capability_providers import (
    SourceArtifactProvider,
    LiveDataProvider,
    get_capability_provider,
)

# For a DEVELOPMENT agent:
provider = get_capability_provider(OperatingMode.DEVELOPMENT)
# → SourceArtifactProvider (can ONLY access: filesystem, git, test runners)
# → has NO method for accessing live patient data
# → cross-mode access is IMPOSSIBLE by construction

# For a RUNTIME agent:
provider = get_capability_provider(OperatingMode.RUNTIME)
# → LiveDataProvider (can ONLY access: appointment API, billing API, vitals API)
# → has NO method for accessing source code repos
```

### PHI Redaction (`security/redaction.py`)

All output is scrubbed before persistence:

```python
from maos.security.redaction import redact_phi, PHI_MARKER_KEYS

# Before writing to audit log, telemetry, or error reports:
safe_data = redact_phi({
    "task_id": "01JFGK...",           # safe — kept
    "patient_name": "John Smith",      # PHI — REDACTED
    "ssn": "123-45-6789",             # PHI — REDACTED
    "api_key": "<REDACTED>",           # secret — REDACTED
    "findings": "The code has issues", # safe — kept
})

# Result:
# {
#   "task_id": "01JFGK...",
#   "patient_name": "[REDACTED]",
#   "ssn": "[REDACTED]",
#   "api_key": "[REDACTED]",
#   "findings": "The code has issues",
# }
```

---

## Implementation Deep Dive — Observability

### Setting Up Observability (Application Startup)

```python
from maos.observability import setup_observability, instrument_fastapi

# Called once at FastAPI app startup:
setup_observability(
    service_name="maos",
    environment="production",
    release="maos@0.1.0",
)

# Then instrument the FastAPI app:
app = create_app()
instrument_fastapi(app)

# Now you get automatically:
# - Structured JSON logs with trace_id, task_id, tenant_id
# - OTel distributed traces for every request
# - Prometheus metrics (tasks, model calls, MCP invocations)
# - Sentry error capture with PHI scrubbing (if SENTRY_DSN set)
# - LangSmith/Langfuse agent traces (if API keys set)
```

### Using the Logger Throughout Code

```python
from maos.observability import get_logger, set_task_id, set_tenant_id

logger = get_logger(__name__)

# Set correlation context (auto-injected into all subsequent logs)
set_task_id("01JFGK...")
set_tenant_id("clinic-001")

# Log an event — automatically includes trace_id, task_id, tenant_id
logger.info(
    "agent.selected",
    agent_id="security-backend-001",
    skill="security-audit",
    platform="BACKEND",
)
# Output:
# {"event":"agent.selected","agent_id":"security-backend-001",
#  "skill":"security-audit","platform":"BACKEND",
#  "trace_id":"abc123...","task_id":"01JFGK...",
#  "tenant_id":"clinic-001","level":"info",
#  "timestamp":"2026-06-27T10:30:15.123Z"}
```

### Agent-Level Tracing

```python
from maos.observability import AgentTracer

tracer = AgentTracer()

# At agent execution start:
tracer.trace_agent_start(
    agent_id="debugger-mobile-001",
    task_id="01JFGK...",
    sub_subtask_id="sst-042",
)

# Each reasoning step:
tracer.trace_reasoning_step(
    agent_id="debugger-mobile-001",
    task_id="01JFGK...",
    step_index=3,
    description="Analyzing crash stack trace",
)

# Tool invocations:
tracer.trace_tool_invocation(
    agent_id="debugger-mobile-001",
    task_id="01JFGK...",
    tool_name="filesystem_read",
    status="success",
)

# Model calls:
tracer.trace_model_call(
    agent_id="debugger-mobile-001",
    task_id="01JFGK...",
    provider="anthropic",
    model="claude-sonnet-4-20250514",
    tokens=2500,
)

# On error — also captures to Sentry:
tracer.trace_agent_error(
    agent_id="debugger-mobile-001",
    task_id="01JFGK...",
    error=exception,
)
```

---

## Integration Guide — Connecting Your Platform Systems


### Integrating from the NestJS Backend

```typescript
// In your NestJS service:
import { HttpService } from '@nestjs/axios';

@Injectable()
export class MaosService {
  constructor(private readonly http: HttpService) {}

  async submitTask(dto: CreateTaskDto, tenantId: string): Promise<string> {
    const response = await this.http.axiosRef.post(
      `${process.env.MAOS_URL}/v1/tasks`,
      {
        mode: dto.mode,           // "DEVELOPMENT" or "RUNTIME"
        title: dto.title,
        description: dto.description,
        payload: dto.payload,
        token_budget: dto.tokenBudget || 100000,
      },
      {
        headers: {
          'Authorization': `Bearer ${await this.getServiceToken()}`,
          'X-Tenant-Id': tenantId,
          'X-Auth-Scope': 'tasks:write',
          'Content-Type': 'application/json',
        },
      }
    );
    return response.data.task_id;
  }

  async getTaskStatus(taskId: string): Promise<TaskResult> {
    const response = await this.http.axiosRef.get(
      `${process.env.MAOS_URL}/v1/tasks/${taskId}`,
      {
        headers: {
          'Authorization': `Bearer ${await this.getServiceToken()}`,
        },
      }
    );
    return response.data;
  }

  // Poll until completion (with timeout)
  async waitForCompletion(taskId: string, timeoutMs = 300000): Promise<TaskResult> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const result = await this.getTaskStatus(taskId);
      if (['completed', 'permanently_failed'].includes(result.state)) {
        return result;
      }
      await new Promise(r => setTimeout(r, 5000)); // poll every 5s
    }
    throw new Error(`Task ${taskId} did not complete within timeout`);
  }
}
```

### Integrating from the Next.js Web Frontend

```typescript
// lib/maos-client.ts
const MAOS_URL = process.env.NEXT_PUBLIC_MAOS_URL || 'https://maos.your-domain.io';

export async function submitCodeReview(
  scope: string[],
  platform: 'BACKEND' | 'WEB' | 'MOBILE',
  token: string,
  tenantId: string,
) {
  const response = await fetch(`${MAOS_URL}/v1/tasks`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-Tenant-Id': tenantId,
      'X-Auth-Scope': 'tasks:write',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      mode: 'DEVELOPMENT',
      title: `Code review: ${scope.join(', ')}`,
      description: `Automated code review of the specified files/directories`,
      payload: {
        target_system: platform,
        scope: scope,
        review_type: 'general',
      },
      token_budget: 50000,
    }),
  });

  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After') || '30';
    throw new Error(`System busy. Retry after ${retryAfter}s`);
  }

  if (!response.ok) {
    throw new Error(`MAOS error: ${response.status}`);
  }

  return response.json(); // { task_id, status: "accepted" }
}
```

### Integrating from the Expo Mobile App

```typescript
// services/maos.ts (React Native / Expo)
import { getAuthToken } from './auth';

const MAOS_URL = process.env.EXPO_PUBLIC_MAOS_URL;

export async function requestAppointmentHelp(
  patientId: string,
  action: 'reschedule' | 'cancel' | 'book',
  details: Record<string, any>,
  tenantId: string,
) {
  const token = await getAuthToken();

  const response = await fetch(`${MAOS_URL}/v1/tasks`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-Tenant-Id': tenantId,
      'X-Auth-Scope': 'tasks:write,appointments:manage',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      mode: 'RUNTIME',
      title: `${action} appointment`,
      description: `Patient requests to ${action} their appointment`,
      payload: {
        patient_id: `ref:${patientId}`,  // referenced by ID, not raw PHI
        action: action,
        ...details,
      },
      token_budget: 10000,
    }),
  });

  if (!response.ok) {
    if (response.status === 429) {
      // Handle backpressure — show "try again later" to user
      return { error: 'busy', retryAfter: 30 };
    }
    throw new Error(`MAOS error: ${response.status}`);
  }

  return response.json();
}
```

---

## Docker Compose — Local Development Stack

For convenience, here's a complete docker-compose setup for local development:

```yaml
# docker-compose.local.yml — full local development stack
# Usage: docker compose -f docker-compose.local.yml up -d
#
# For Coolify production deployment, use docker-compose.coolify.yml
# which only contains app services (api, worker, dashboard).
# Databases are managed externally on Coolify.

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: maos
      POSTGRES_PASSWORD: maos
      POSTGRES_DB: maos
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U maos"]
      interval: 5s
      timeout: 5s
      retries: 5

  dragonfly:
    image: docker.dragonflydb.io/dragonflydb/dragonfly:latest
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      MAOS_POSTGRES_DSN: postgresql://maos:maos@postgres:5432/maos
      MAOS_REDIS_URL: redis://dragonfly:6379/0
      MAOS_BROKER_URL: redis://dragonfly:6379/1
      MAOS_DRAGONFLY_CACHE_URL: redis://dragonfly:6379/2
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      SECRETS_BACKEND: env
    depends_on:
      postgres:
        condition: service_healthy
      dragonfly:
        condition: service_healthy

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      MAOS_POSTGRES_DSN: postgresql://maos:maos@postgres:5432/maos
      MAOS_REDIS_URL: redis://dragonfly:6379/0
      MAOS_BROKER_URL: redis://dragonfly:6379/1
      MAOS_DRAGONFLY_CACHE_URL: redis://dragonfly:6379/2
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      SECRETS_BACKEND: env
    depends_on:
      postgres:
        condition: service_healthy
      dragonfly:
        condition: service_healthy

  migrate:
    build:
      context: .
      dockerfile: Dockerfile.worker
    command: ["python", "-m", "maos.migrations.run"]
    environment:
      MAOS_POSTGRES_HOST: postgres
      MAOS_POSTGRES_PORT: "5432"
      MAOS_POSTGRES_DB: maos
      MAOS_POSTGRES_USER: maos
      MAOS_POSTGRES_PASSWORD: maos
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  pgdata:
```

**Usage:**
```bash
# Start everything:
docker compose up -d

# Run migrations:
docker compose run --rm migrate

# View logs:
docker compose logs -f api worker

# Submit a test task:
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -H "X-Tenant-Id: clinic-001" \
  -d '{"mode":"DEVELOPMENT","title":"Test task","description":"Hello MAOS","payload":{},"token_budget":1000}'

# Tear down:
docker compose down -v
```

---

## Testing

### Running All Tests

```bash
# Full test suite
uv run pytest

# Property tests only (Hypothesis)
uv run pytest tests/property/ -v

# Unit tests only
uv run pytest tests/unit/ -v

# Integration tests (requires Postgres + Redis)
uv run pytest tests/integration/ -v

# With coverage
uv run pytest --cov=maos --cov-report=html
```

### Writing a Property Test

Each property test validates a formal correctness property from the design:

```python
# tests/property/test_decomposition.py
from hypothesis import given, settings
from hypothesis import strategies as st
from maos.core.decomposition import decompose_task_to_subtasks
from maos.contracts.work_units import Task, OperatingMode, PlatformSystem

# Feature: multi-agent-orchestration-system, Property 1:
# Task decomposition produces single-system, mode-propagated, traceable Subtasks

@settings(max_examples=100)
@given(task=st.builds(Task, ...))  # generate random valid Tasks
def test_decomposition_produces_single_system_subtasks(task: Task):
    subtasks = decompose_task_to_subtasks(task)

    for subtask in subtasks:
        # Each subtask targets exactly one platform
        assert subtask.platform_system in PlatformSystem
        # Mode is propagated from parent Task
        assert subtask.mode == task.mode
        # Tenant is propagated
        assert subtask.tenant_id == task.tenant_id
        # Traceable back to originating Task
        assert subtask.task_id == task.task_id
```

### Linting and Type Checking

```bash
# Lint (ruff — fast Python linter)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Type check (mypy — strict mode)
uv run mypy

# Both must pass before any PR is merged
```

---

## Extending MAOS — Common Patterns

### Adding a New Platform System

```python
# 1. Add to the enum (contracts/work_units.py):
class PlatformSystem(str, Enum):
    BACKEND = "BACKEND"
    WEB = "WEB"
    MOBILE = "MOBILE"
    DESKTOP = "DESKTOP"  # NEW

# 2. Register agents for the new platform:
await registry.register(SubagentSpec(
    subagent_id="code-reviewer-desktop-001",
    role="Code_Reviewer",
    platform_system=PlatformSystem.DESKTOP,
    mode=OperatingMode.DEVELOPMENT,
    ...
))

# 3. That's it — the Root Orchestrator will automatically
#    route DESKTOP subtasks to the new agents via the registry.
#    No orchestrator code changes needed.
```

### Adding a New Subagent Role

```python
# Just register with a new role name:
await registry.register(SubagentSpec(
    subagent_id="documentation-writer-backend-001",
    role="Documentation_Writer",  # new role
    platform_system=PlatformSystem.BACKEND,
    mode=OperatingMode.DEVELOPMENT,
    skills=[
        Skill(skill_id="write-docs", ...),
        Skill(skill_id="generate-api-docs", ...),
    ],
    capability=AgenticCapability(max_reasoning_steps=50, max_tool_invocations=20),
    mcp_allow_list=["filesystem_read", "filesystem_write", "git_log"],
))
```

### Adding a New MCP Tool Server

1. Deploy the MCP server as a Kubernetes pod in the `maos` namespace
2. Label it: `app.kubernetes.io/component: mcp-server`
3. Register tools with their descriptors
4. Add tool names to appropriate agents' `mcp_allow_list`
5. Update NetworkPolicy if the tool needs external access

---

## Glossary

| Term | Definition |
|------|-----------|
| **Task** | A high-level unit of work submitted by a Platform System |
| **Subtask** | A platform-specific portion of a Task (one per involved platform) |
| **SubSubtask** | An agent-assignable unit of work within a Subtask |
| **Root Orchestrator** | Top-level LangGraph graph that decomposes and routes Tasks |
| **Sub-Orchestrator** | Platform-specific graph that manages Subtasks and agents |
| **Subagent** | An AI agent with declared Skills and bounded capabilities |
| **Skill** | A declared capability of a Subagent (input/output contracts) |
| **MCP** | Model Context Protocol — standardized tool invocation interface |
| **Operating Mode** | DEVELOPMENT (source code) or RUNTIME (live data) |
| **Platform System** | BACKEND, WEB, or MOBILE |
| **Tenant** | A clinic/organization (multi-tenant isolation boundary) |
| **PHI** | Protected Health Information (HIPAA-regulated patient data) |
| **BAA** | Business Associate Agreement (required for PHI processing) |
| **Checkpoint** | A Postgres-persisted graph state snapshot for resume |
| **Shared_Context** | Redis-backed per-Task data shared between agents |
| **Semantic_Memory** | pgvector-backed long-term knowledge store |
| **Human_Approval** | A LangGraph interrupt requiring explicit human action |
| **Delegation** | When one agent routes part of its work to another agent's skill |
| **Backpressure** | 429 response when system is at capacity |
| **Circuit Breaker** | Fast-fail pattern when a dependency is unhealthy |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-06-27 | Initial implementation — all core tasks complete |

---

## License

Proprietary — Healthcare Platform Team

---

*Generated by MAOS spec-driven development workflow. 95/173 tasks completed (78 optional test tasks deferred).*
