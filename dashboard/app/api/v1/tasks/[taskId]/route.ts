import { NextResponse } from "next/server";
import { MOCK_TASKS } from "@/app/api/mock/data";

export async function GET(
  _request: Request,
  { params }: { params: { taskId: string } }
) {
  const task = MOCK_TASKS.find((t) => t.task_id === params.taskId) ?? MOCK_TASKS[0];
  return NextResponse.json({
    task,
    subtasks: [
      {
        subtask_id: "st-001-a",
        task_id: task.task_id,
        platform_system: "BACKEND",
        mode: task.mode,
        state: task.state,
        assigned_orchestrator_id: "orch-backend",
        started_at: task.created_at,
        completed_at: task.state === "completed" ? task.updated_at : undefined,
      },
      {
        subtask_id: "st-001-b",
        task_id: task.task_id,
        platform_system: "WEB",
        mode: task.mode,
        state: task.state === "completed" ? "completed" : "in_progress",
        assigned_orchestrator_id: "orch-web",
        started_at: task.created_at,
      },
    ],
    subSubtasks: [
      {
        sub_subtask_id: "ss-001-a",
        subtask_id: "st-001-a",
        task_id: task.task_id,
        platform_system: "BACKEND",
        mode: task.mode,
        required_skill: "fastapi",
        assigned_subagent_id: "agent-backend-001",
        state: task.state,
        is_sensitive: false,
        attempts: 1,
        started_at: task.created_at,
        completed_at: task.state === "completed" ? task.updated_at : undefined,
      },
      {
        sub_subtask_id: "ss-001-b",
        subtask_id: "st-001-b",
        task_id: task.task_id,
        platform_system: "WEB",
        mode: task.mode,
        required_skill: "react",
        assigned_subagent_id: "agent-web-001",
        state: "in_progress",
        is_sensitive: false,
        attempts: 1,
        started_at: task.created_at,
      },
    ],
  });
}
