"use client";

/**
 * Single agent card in the hierarchy tree.
 *
 * Shows a status dot with a visible status label (green = available,
 * yellow = draining, gray = removed), an operating mode badge, and the
 * count of active sub_subtask assignments. The card header is a disclosure
 * button that expands the agent's detail panel.
 *
 * @module components/agents/agent-node
 */

import * as React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ModeBadge } from "@/components/tasks/task-row";
import { AgentDetail } from "@/components/agents/agent-detail";
import type { AgentNode } from "@/types";

/**
 * Status dot colors keyed by agent availability status.
 *
 * Shades clear 3:1 against the card surface in both themes (SC 1.4.11).
 * Each dot is rendered alongside a visible status word, so the color is
 * redundant rather than load-bearing (SC 1.4.1).
 */
export const AGENT_STATUS_DOT_CLASSES: Record<AgentNode["status"], string> = {
  available: "bg-green-600 dark:bg-green-500",
  draining: "bg-yellow-700 dark:bg-yellow-500",
  removed: "bg-gray-500 dark:bg-gray-400",
};

/** Props for {@link AgentNodeCard}. */
export interface AgentNodeCardProps {
  /** The agent to render. */
  agent: AgentNode;
  /** Whether the detail panel is expanded. */
  expanded: boolean;
  /** Called when the card is activated to toggle expansion. */
  onToggle: (agentId: string) => void;
}

/**
 * Agent card with live status indicator and expandable detail.
 *
 * @example
 * ```tsx
 * <AgentNodeCard agent={agent} expanded={false} onToggle={setSelected} />
 * ```
 */
export function AgentNodeCard({
  agent,
  expanded,
  onToggle,
}: AgentNodeCardProps) {
  const detailId = `agent-detail-${agent.agent_id}`;
  const assignmentCount = agent.active_assignments?.length ?? 0;
  const Chevron = expanded ? ChevronDown : ChevronRight;

  return (
    <li className="rounded-lg border border-input bg-card">
      <button
        type="button"
        onClick={() => onToggle(agent.agent_id)}
        aria-expanded={expanded}
        aria-controls={detailId}
        className="flex min-h-touch w-full flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Chevron
          className="h-4 w-4 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        <span
          className={cn(
            "h-2.5 w-2.5 shrink-0 rounded-full",
            AGENT_STATUS_DOT_CLASSES[agent.status],
          )}
          aria-hidden="true"
        />
        <span className="min-w-0 truncate font-medium">{agent.agent_id}</span>
        <span className="truncate text-xs text-muted-foreground">
          {agent.role}
        </span>
        {/*
          Visible status text next to the dot: status must not rely on the
          dot color alone (SC 1.4.1).
        */}
        <span className="truncate text-xs font-medium text-muted-foreground">
          <span className="sr-only">Status: </span>
          {agent.status}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <ModeBadge mode={agent.mode} />
          <Badge
            variant="outline"
            className={cn(
              "whitespace-nowrap",
              assignmentCount > 0
                ? "border-blue-500/40 bg-blue-500/15 text-blue-700 dark:text-blue-300"
                : "text-muted-foreground",
            )}
          >
            {assignmentCount} active
          </Badge>
        </span>
      </button>

      <div id={detailId} hidden={!expanded}>
        {expanded ? <AgentDetail agent={agent} /> : null}
      </div>
    </li>
  );
}
