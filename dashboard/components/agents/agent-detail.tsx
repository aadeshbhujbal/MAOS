"use client";

/**
 * Agent detail panel.
 *
 * Displays declared skills, agentic capability budgets (reasoning steps and
 * tool invocations), the MCP allow-list, active assignments, and the
 * selection priority with the deterministic selection rule.
 *
 * @module components/agents/agent-detail
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import type { AgentNode } from "@/types";

/** Props for {@link AgentDetail}. */
export interface AgentDetailProps {
  /** Agent whose configuration is displayed. */
  agent: AgentNode;
}

/** A labelled block of badge chips, with an empty-state fallback. */
function ChipList({
  label,
  values,
  emptyText,
}: {
  label: string;
  values: string[];
  emptyText: string;
}) {
  return (
    <div className="space-y-1">
      <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </h4>
      {values.length === 0 ? (
        <p className="text-xs text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <li key={value}>
              <Badge variant="secondary" className="font-mono text-[11px]">
                {value}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A labelled numeric budget value. */
function BudgetStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-mono text-sm font-medium">{value}</dd>
    </div>
  );
}

/**
 * Expanded configuration view for a single agent.
 *
 * @example
 * ```tsx
 * <AgentDetail agent={agent} />
 * ```
 */
export function AgentDetail({ agent }: AgentDetailProps) {
  return (
    <div className="space-y-4 border-t border-border px-3 py-3">
      <ChipList
        label="Declared skills"
        values={agent.skills ?? []}
        emptyText="No skills declared."
      />

      <div className="space-y-1">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Capability budgets
        </h4>
        <dl className="grid gap-2 sm:grid-cols-2">
          <BudgetStat
            label="Max reasoning steps"
            value={agent.max_reasoning_steps}
          />
          <BudgetStat
            label="Max tool invocations"
            value={agent.max_tool_invocations}
          />
        </dl>
      </div>

      <ChipList
        label="MCP allow-list"
        values={agent.mcp_allow_list ?? []}
        emptyText="No MCP servers permitted for this agent."
      />

      <ChipList
        label="Active assignments"
        values={agent.active_assignments ?? []}
        emptyText="No active sub_subtask assignments."
      />

      <div className="space-y-1">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Selection priority
        </h4>
        <p className="font-mono text-sm font-medium">
          {agent.selection_priority}
        </p>
        <p className="text-xs text-muted-foreground">
          Deterministic selection rule: among agents matching the required
          skill, platform system, and operating mode, the available agent with
          the lowest selection priority is chosen; ties break on agent_id in
          ascending lexicographic order.
        </p>
      </div>
    </div>
  );
}
