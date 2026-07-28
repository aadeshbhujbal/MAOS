# Requirements Document

## Introduction

The MAOS Dashboard Universal is a full-featured Next.js 14+ web application that provides a unified interface for interacting with the Multi-Agent Orchestration System (MAOS). The dashboard enables users to submit tasks via a chat interface, manage projects with Git clone integration, monitor real-time agent execution via WebSocket streaming, review task history, approve sensitive agent actions, upload knowledge base documents, and observe the live agent execution feed. The system extends the existing MAOS FastAPI backend with WebSocket streaming and project management endpoints, and integrates into the existing Docker Compose deployment.

## Glossary

- **Dashboard**: The Next.js 14+ web application providing the user interface for MAOS interaction
- **MAOS_API**: The existing FastAPI backend service exposing REST endpoints for task management at port 8000
- **WebSocket_Proxy**: A Next.js API route that proxies WebSocket connections from the Dashboard to the MAOS_API WebSocket endpoint
- **WebSocket_Endpoint**: A new FastAPI WebSocket endpoint on the MAOS_API that streams real-time agent execution events to connected clients
- **Project**: A registered code repository within MAOS, consisting of a name, Git remote URL, local clone path, and associated metadata
- **Project_Registry**: The backend module responsible for CRUD operations and Git clone management for Projects
- **Chat_Interface**: The primary Dashboard UI component where users compose and submit tasks to MAOS and receive streamed responses
- **Agent_Feed**: A real-time Dashboard UI panel displaying live execution events from active agents including reasoning steps, tool invocations, and status transitions
- **Approval_UI**: A Dashboard UI component that presents pending human-approval requests from agents and allows users to approve or reject sensitive actions
- **Knowledge_Upload**: A Dashboard UI component enabling users to upload documents (PDF, text, code files) to the MAOS knowledge base
- **Task_History**: A Dashboard UI panel listing previously submitted tasks with their status and results
- **Auth_Token**: A Bearer token passed from the Dashboard to the MAOS_API for authentication and authorization
- **Project_Sidebar**: A Dashboard UI navigation panel listing registered Projects and allowing selection of the active project context

## Requirements

### Requirement 1: Chat Interface Task Submission

**User Story:** As a developer, I want to submit tasks to MAOS through a chat interface, so that I can interact with the orchestration system conversationally.

#### Acceptance Criteria

1. THE Dashboard SHALL render a Chat_Interface component with a text input field and a submit control on the main content area.
2. WHEN a user submits a message in the Chat_Interface, THE Dashboard SHALL send a POST request to the MAOS_API `/v1/tasks` endpoint with the message content as the task description.
3. WHEN a user submits a message in the Chat_Interface, THE Dashboard SHALL include the Auth_Token as a Bearer token in the Authorization header of the request.
4. WHEN a user submits a message in the Chat_Interface, THE Dashboard SHALL include the X-Tenant-Id and X-Auth-Scope headers derived from the authenticated session.
5. WHEN the MAOS_API returns a 202 Accepted response, THE Dashboard SHALL display the accepted task_id in the Chat_Interface as a confirmation message.
6. IF the MAOS_API returns a 401 or 403 error, THEN THE Dashboard SHALL display an authentication error message in the Chat_Interface and prompt the user to re-authenticate.
7. IF the MAOS_API returns a 429 error, THEN THE Dashboard SHALL display a rate-limit message in the Chat_Interface indicating the system is at capacity and show the Retry-After duration.

### Requirement 2: WebSocket Real-Time Streaming

**User Story:** As a developer, I want to see real-time agent execution progress, so that I can monitor what MAOS agents are doing without polling.

#### Acceptance Criteria

1. THE MAOS_API SHALL expose a WebSocket endpoint at `/ws/tasks/{task_id}/stream` that streams execution events for a given task.
2. WHEN a WebSocket client connects to the WebSocket_Endpoint, THE MAOS_API SHALL validate the Auth_Token provided as a query parameter or in the initial connection headers.
3. IF a WebSocket client provides an invalid or missing Auth_Token, THEN THE MAOS_API SHALL reject the connection with a 1008 (Policy Violation) close code.
4. WHILE a task is in an active execution state (assigned or in_progress), THE WebSocket_Endpoint SHALL emit JSON-formatted events containing event_type, timestamp, agent_id, and payload fields.
5. THE WebSocket_Endpoint SHALL emit events for the following event types: `reasoning_step`, `tool_invocation`, `tool_result`, `subtask_created`, `status_change`, `approval_requested`, and `error`.
6. WHEN a task reaches a terminal state (completed, failed, or permanently_failed), THE WebSocket_Endpoint SHALL emit a final `task_complete` event and close the connection with code 1000 (Normal Closure).
7. THE Dashboard SHALL provide a WebSocket_Proxy API route at `/api/ws/tasks/[taskId]/stream` that proxies WebSocket connections to the MAOS_API WebSocket_Endpoint.
8. WHEN the WebSocket_Proxy receives a connection, THE Dashboard SHALL forward the Auth_Token from the client session to the upstream MAOS_API WebSocket_Endpoint.

### Requirement 3: Project Registration and Management

**User Story:** As a developer, I want to register Git repositories as projects in MAOS, so that agents have context about which codebase to work on.

#### Acceptance Criteria

1. THE MAOS_API SHALL expose a REST endpoint `POST /v1/projects` that accepts a project name, Git remote URL, and optional branch name to register a new Project.
2. WHEN a new Project is registered via `POST /v1/projects`, THE Project_Registry SHALL perform a full Git clone of the specified repository to a server-side storage directory.
3. WHEN the Git clone operation completes successfully, THE Project_Registry SHALL store the Project metadata (project_id, name, git_url, branch, clone_path, created_at, tenant_id) in the Postgres database.
4. IF the Git clone operation fails (invalid URL, authentication failure, network error), THEN THE Project_Registry SHALL return a 422 error with a descriptive message indicating the clone failure reason.
5. THE MAOS_API SHALL expose a REST endpoint `GET /v1/projects` that returns a list of all Projects belonging to the authenticated tenant.
6. THE MAOS_API SHALL expose a REST endpoint `GET /v1/projects/{project_id}` that returns the metadata for a single Project.
7. THE MAOS_API SHALL expose a REST endpoint `DELETE /v1/projects/{project_id}` that removes the Project record and deletes the cloned repository from storage.
8. THE MAOS_API SHALL expose a REST endpoint `PUT /v1/projects/{project_id}` that allows updating the Project name and triggering a fresh Git pull on the existing clone.
9. WHEN a task is submitted with a `project_id` in the payload, THE MAOS_API SHALL associate the task with the corresponding Project clone path for agent access.

### Requirement 4: Project Sidebar Navigation

**User Story:** As a developer, I want a sidebar listing my registered projects, so that I can quickly switch context between different codebases.

#### Acceptance Criteria

1. THE Dashboard SHALL render a Project_Sidebar component on the left side of the layout displaying a list of registered Projects.
2. WHEN the Dashboard loads, THE Project_Sidebar SHALL fetch the project list from the MAOS_API `GET /v1/projects` endpoint using the Auth_Token.
3. WHEN a user selects a Project in the Project_Sidebar, THE Dashboard SHALL set that Project as the active context for subsequent task submissions.
4. WHILE a Project is selected as the active context, THE Dashboard SHALL include the project_id in the payload of all task submissions from the Chat_Interface.
5. THE Project_Sidebar SHALL display each Project entry with its name, Git remote URL (truncated), and last-updated timestamp.
6. THE Project_Sidebar SHALL provide a control to register a new Project that opens a registration form accepting name, Git URL, and branch fields.
7. WHEN the user submits the new Project registration form, THE Dashboard SHALL send a POST request to `POST /v1/projects` and refresh the Project_Sidebar list upon success.

### Requirement 5: Task History Panel

**User Story:** As a developer, I want to view my previously submitted tasks and their results, so that I can track work progress and revisit outcomes.

#### Acceptance Criteria

1. THE Dashboard SHALL render a Task_History panel accessible from the main navigation that lists previously submitted tasks.
2. WHEN the Task_History panel is opened, THE Dashboard SHALL fetch the task list from the MAOS_API using the `GET /v1/tasks` endpoint filtered by the authenticated tenant.
3. THE Task_History panel SHALL display each task entry with its title, status (assigned, in_progress, completed, failed), submission timestamp, and associated Project name.
4. WHEN a user selects a task in the Task_History panel, THE Dashboard SHALL display the full task details and aggregated results in the main content area.
5. WHILE a task is in an active state (assigned or in_progress), THE Task_History panel SHALL display an animated status indicator for that task entry.
6. THE Task_History panel SHALL support filtering by task status and sorting by submission date.

### Requirement 6: Approval Interface

**User Story:** As a developer, I want to approve or reject sensitive agent actions from the dashboard, so that I can maintain control over destructive operations.

#### Acceptance Criteria

1. THE Dashboard SHALL render an Approval_UI component that displays pending approval requests from MAOS agents.
2. WHEN the WebSocket_Endpoint emits an `approval_requested` event, THE Dashboard SHALL display the approval request in the Approval_UI with the action description, agent_id, and risk level.
3. THE Approval_UI SHALL provide approve and reject controls for each pending approval request.
4. WHEN a user approves a request in the Approval_UI, THE Dashboard SHALL send a POST request to the MAOS_API approval endpoint with the approval decision and the user's Auth_Token.
5. WHEN a user rejects a request in the Approval_UI, THE Dashboard SHALL send a POST request to the MAOS_API approval endpoint with the rejection decision and an optional reason field.
6. WHEN an approval decision is submitted successfully, THE Approval_UI SHALL remove the resolved request from the pending list and display a confirmation status.
7. IF the approval request expires or the task is cancelled before a decision, THEN THE Approval_UI SHALL mark the request as expired and disable the approve/reject controls.

### Requirement 7: Knowledge Base Upload

**User Story:** As a developer, I want to upload documents to the MAOS knowledge base from the dashboard, so that agents have access to relevant project documentation.

#### Acceptance Criteria

1. THE Dashboard SHALL render a Knowledge_Upload component accessible from the main navigation.
2. THE Knowledge_Upload component SHALL accept file uploads with supported formats: PDF, plain text (.txt), Markdown (.md), Python (.py), JavaScript (.js), TypeScript (.ts), Java (.java), Go (.go), and Rust (.rs).
3. WHEN a user selects files for upload, THE Dashboard SHALL validate that each file is within the 10 MB size limit before sending.
4. IF a user selects a file exceeding 10 MB, THEN THE Dashboard SHALL display an error message indicating the file size limit and reject the file.
5. WHEN the user confirms the upload, THE Dashboard SHALL send a multipart POST request to the MAOS_API knowledge ingestion endpoint with the file data and the Auth_Token.
6. WHILE a file upload is in progress, THE Knowledge_Upload component SHALL display a progress indicator showing upload percentage.
7. WHEN the upload completes successfully, THE Knowledge_Upload component SHALL display a success confirmation with the document_id and ingestion status.
8. THE Knowledge_Upload component SHALL allow associating uploaded documents with a specific Project from the Project_Sidebar selection.

### Requirement 8: Agent Execution Feed

**User Story:** As a developer, I want a live feed showing what all active agents are doing, so that I can observe the orchestration system in action.

#### Acceptance Criteria

1. THE Dashboard SHALL render an Agent_Feed panel that displays real-time execution events from all active tasks for the authenticated tenant.
2. WHEN the Agent_Feed panel is opened, THE Dashboard SHALL establish a WebSocket connection to the MAOS_API to receive aggregated execution events.
3. THE Agent_Feed SHALL display each event with the agent role, event type, timestamp, and a summary of the event payload.
4. THE Agent_Feed SHALL visually distinguish between event types using color coding: reasoning steps in blue, tool invocations in orange, results in green, errors in red, and approvals in yellow.
5. WHILE the Agent_Feed panel is visible, THE Dashboard SHALL auto-scroll to the most recent event entry unless the user has manually scrolled upward.
6. WHEN the user scrolls upward in the Agent_Feed, THE Dashboard SHALL pause auto-scrolling and display a control to resume auto-scroll to the latest events.
7. THE Agent_Feed SHALL support filtering events by agent role and event type.
8. THE Agent_Feed SHALL retain a rolling buffer of the most recent 500 events in memory to maintain rendering performance.

### Requirement 9: Authentication Passthrough

**User Story:** As a developer, I want the dashboard to pass my authentication token to MAOS without managing separate credentials, so that I have a seamless login experience.

#### Acceptance Criteria

1. THE Dashboard SHALL accept a Bearer Auth_Token via an environment variable or login form and store it in the client session.
2. WHEN the Dashboard makes any request to the MAOS_API, THE Dashboard SHALL attach the Auth_Token as a Bearer token in the Authorization header.
3. WHEN the Dashboard makes any request to the MAOS_API, THE Dashboard SHALL include the X-Tenant-Id header with the value configured in the Dashboard environment or derived from the Auth_Token claims.
4. WHEN the Dashboard makes any request to the MAOS_API, THE Dashboard SHALL include the X-Auth-Scope header with the appropriate permission scopes for the operation.
5. IF the MAOS_API returns a 401 Unauthorized response to any request, THEN THE Dashboard SHALL clear the stored Auth_Token and redirect the user to the login form.
6. THE Dashboard SHALL store the Auth_Token in an HTTP-only secure cookie or server-side session to prevent client-side JavaScript access.

### Requirement 10: Docker Compose Integration

**User Story:** As a DevOps engineer, I want the dashboard to be deployable alongside the existing MAOS services via Docker Compose, so that the entire system can be started with a single command.

#### Acceptance Criteria

1. THE Dashboard SHALL be defined as a service named `dashboard` in the Docker Compose configuration file alongside the existing api, worker, redis, postgres, and neo4j services.
2. THE Dashboard service SHALL expose port 3000 on the host mapped to port 3000 in the container.
3. THE Dashboard service SHALL depend on the api service being healthy before starting.
4. THE Dashboard service SHALL receive the MAOS_API base URL via an environment variable `NEXT_PUBLIC_MAOS_API_URL` defaulting to `http://api:8000`.
5. THE Dashboard service SHALL receive the WebSocket URL via an environment variable `NEXT_PUBLIC_MAOS_WS_URL` defaulting to `ws://api:8000`.
6. THE Dashboard service SHALL be connected to the same `maos-network` bridge network as the existing services.
7. THE Dashboard service SHALL have resource limits configured at a maximum of 512 MB memory and 0.5 CPU.
8. THE Dashboard service SHALL include a health check that verifies the Next.js server is responding on port 3000.

### Requirement 11: Dashboard Layout and Navigation

**User Story:** As a developer, I want a well-organized dashboard layout with clear navigation, so that I can efficiently access all features.

#### Acceptance Criteria

1. THE Dashboard SHALL use the Next.js 14+ App Router for page routing and layout composition.
2. THE Dashboard SHALL render a responsive layout with a collapsible Project_Sidebar on the left, a main content area in the center, and an optional right panel for the Agent_Feed.
3. THE Dashboard SHALL provide a top navigation bar with links to Chat_Interface, Task_History, Knowledge_Upload, and Approval_UI views.
4. WHEN the viewport width is below 768 pixels, THE Dashboard SHALL collapse the Project_Sidebar into a hamburger menu toggle.
5. THE Dashboard SHALL maintain the selected Project context across all navigation transitions within the same session.
6. THE Dashboard SHALL display a connection status indicator showing whether the WebSocket connection to MAOS_API is active, disconnected, or reconnecting.

### Requirement 12: WebSocket Connection Resilience

**User Story:** As a developer, I want WebSocket connections to automatically reconnect on failure, so that I do not lose real-time updates during brief network interruptions.

#### Acceptance Criteria

1. WHEN the WebSocket connection between the Dashboard and the WebSocket_Proxy is dropped unexpectedly, THE Dashboard SHALL attempt automatic reconnection using exponential backoff starting at 1 second with a maximum delay of 30 seconds.
2. WHILE the Dashboard is attempting WebSocket reconnection, THE Dashboard SHALL display a visual indicator communicating the reconnecting state to the user.
3. WHEN the WebSocket connection is re-established, THE Dashboard SHALL resume receiving events from the point of reconnection without duplicating previously received events.
4. IF the WebSocket reconnection fails after 5 consecutive attempts, THEN THE Dashboard SHALL display a persistent error notification with a manual reconnect control.
5. WHEN the WebSocket_Proxy loses connection to the upstream MAOS_API WebSocket_Endpoint, THE WebSocket_Proxy SHALL close the client connection with a 1001 (Going Away) code and a descriptive reason.
