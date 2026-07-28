"use client";

/**
 * Agent hierarchy page.
 *
 * Fetches the flat agent registry, builds the Root → Sub-Orchestrators →
 * Subagents tree with `buildAgentTree`, and subscribes to the `agents.*`
 * WebSocket topic for live status and assignment updates.
 *
 * @module app/agents/page
 */

import * as React from "react";
import { ChevronDown, ChevronRight, Network, Server } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AGENT_STATUS_DOT_CLASSES,
  AgentNodeCard,
} from "@/components/agents/agent-node";
import { getAgents } from "@/lib/api/agents";
import { getAuthToken } from "@/lib/api/client";
import { useAgentStore } from "@/lib/stores/agent-store";
import { buildAgentTree } from "@/lib/utils/agent-tree";
import { TOPICS } from "@/lib/ws/subscriptions";
import { useWebSocket } from "@/hooks/use-websocket";
import { useIsDesktop } from "@/hooks/use-media-query";
import type { AgentNode, WSEvent } from "@/types";

/** Loading placeholder for the hierarchy tree. */
function TreeSkeleton() {
  return (
    <div
      className="space-y-3"
      role="status"
      aria-busy="true"
      aria-label="Loading agent hierarchy"
    >
      <Skeleton className="h-12 w-full" />
      {Array.from({ length: 3 }).map((_, index) => (
        <Skeleton key={index} className="h-28 w-full" />
      ))}
    </div>
  );
}

/**
 * Narrow a WebSocket payload into an AgentNode when it carries an agent_id.
 */
function readAgentPayload(payload: Record<string, unknown>): AgentNode | null {
  const agentId = payload["agent_id"];
  if (typeof agentId !== "string" || !agentId) return null;
  return payload as unknown as AgentNode;
}

/** Agent hierarchy page with live streaming updates. */
export default function AgentsPage() {
  const agents = useAgentStore((state) => state.agents);
  const setAgents = useAgentStore((state) => state.setAgents);
  const updateAgent = useAgentStore((state) => state.updateAgent);
  const addAgent = useAgentStore((state) => state.addAgent);

  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [expandedAgentId, setExpandedAgentId] = React.useState<string | null>(
    null,
  );
  const [token, setToken] = React.useState("");

  // Sub-orchestrator branches are collapsed by default below `md` and
  // expanded on desktop (Requirement 9.1). Manual toggles override the
  // breakpoint default for that branch.
  const isDesktop = useIsDesktop();
  const [branchOverrides, setBranchOverrides] = React.useState<
    Record<string, boolean>
  >({});

  const toggleBranch = React.useCallback(
    (orchestratorId: string, currentlyExpanded: boolean) => {
      setBranchOverrides((current) => ({
        ...current,
        [orchestratorId]: !currentlyExpanded,
      }));
    },
    [],
  );

  React.useEffect(() => {
    setToken(getAuthToken());
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    getAgents()
      .then((response) => {
        if (!cancelled) setAgents(response);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load agents");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [setAgents, reloadKey]);

  const handleEvent = React.useCallback(
    (event: WSEvent) => {
      if (!event.topic.startsWith("agents.")) return;
      const agent = readAgentPayload(event.payload);
      if (!agent) return;

      const known = useAgentStore
        .getState()
        .agents.some((a) => a.agent_id === agent.agent_id);
      if (known) {
        updateAgent(agent.agent_id, agent);
      } else {
        addAgent(agent);
      }
    },
    [addAgent, updateAgent],
  );

  useWebSocket({
    token,
    topics: [TOPICS.AGENTS],
    onEvent: handleEvent,
  });

  const tree = React.useMemo(() => buildAgentTree(agents), [agents]);

  const toggleAgent = React.useCallback((agentId: string) => {
    setExpandedAgentId((current) => (current === agentId ? null : agentId));
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">Agent hierarchy</h2>
          <p className="text-sm text-muted-foreground">
            Root orchestrator, platform sub-orchestrators, and their subagents.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setReloadKey((key) => key + 1)}
          disabled={isLoading}
          aria-label="Refresh agent hierarchy"
          aria-busy={isLoading}
        >
          Refresh
        </Button>
      </div>

      {/*
        Low-noise live region for streamed registry changes. Announcing the
        whole tree on every `agents.*` event would be overwhelming, so only
        the roster size is spoken (Requirement 9.2).
      */}
      <p
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {agents.length} agent{agents.length === 1 ? "" : "s"} registered.
      </p>

      {error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load agents: {error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Retry
          </Button>
        </div>
      ) : isLoading ? (
        <TreeSkeleton />
      ) : (
        /*
          The hierarchy is a nested list of disclosure buttons rather than an
          ARIA tree widget: every branch and leaf is a real <button> in the
          natural Tab order with aria-expanded/aria-controls, which is fully
          keyboard operable without needing custom arrow-key focus
          management (Requirement 9.2).
        */
        <div className="space-y-3">
          <h3 className="sr-only">Agent hierarchy</h3>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2">
            <Network
              className="h-4 w-4 text-muted-foreground"
              aria-hidden="true"
            />
            <span className="font-medium">{tree.root.id}</span>
            <Badge variant="outline" className="ml-auto">
              <span className="sr-only">Status: </span>
              {tree.root.status}
            </Badge>
          </div>

          <ul
            aria-label="Platform sub-orchestrators"
            className="ml-2 space-y-3 border-l border-border pl-2 md:ml-4 md:pl-4"
          >
            {tree.sub_orchestrators.map((orchestrator) => {
              const branchExpanded =
                branchOverrides[orchestrator.id] ?? isDesktop;
              const BranchChevron = branchExpanded ? ChevronDown : ChevronRight;
              const branchId = `orchestrator-branch-${orchestrator.id}`;

              return (
                <li key={orchestrator.id}>
                  <button
                    type="button"
                    onClick={() =>
                      toggleBranch(orchestrator.id, branchExpanded)
                    }
                    aria-expanded={branchExpanded}
                    aria-controls={branchId}
                    className="flex min-h-touch w-full flex-wrap items-center gap-2 rounded-lg border border-input bg-card px-3 py-2 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <BranchChevron
                      className="h-4 w-4 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <Server
                      className="h-4 w-4 text-muted-foreground"
                      aria-hidden="true"
                    />
                    <span className="font-medium">
                      {orchestrator.platform_system}
                    </span>
                    <span className="truncate font-mono text-xs text-muted-foreground">
                      {orchestrator.id}
                    </span>
                    <span className="ml-auto flex items-center gap-2">
                      <span
                        className={cn(
                          "h-2.5 w-2.5 rounded-full",
                          AGENT_STATUS_DOT_CLASSES[
                            orchestrator.status as keyof typeof AGENT_STATUS_DOT_CLASSES
                          ] ?? "bg-gray-500 dark:bg-gray-400",
                        )}
                        aria-hidden="true"
                      />
                      <span className="text-xs font-medium text-muted-foreground">
                        <span className="sr-only">Status: </span>
                        {orchestrator.status}
                      </span>
                      <Badge variant="outline">
                        {orchestrator.subagents.length} subagents
                      </Badge>
                    </span>
                  </button>

                  <div id={branchId} hidden={!branchExpanded}>
                    {orchestrator.subagents.length === 0 ? (
                      <p className="ml-4 mt-2 border-l border-border pl-4 text-xs text-muted-foreground">
                        No subagents registered for{" "}
                        {orchestrator.platform_system}.
                      </p>
                    ) : (
                      <ul
                        aria-label={`${orchestrator.platform_system} subagents`}
                        className="ml-2 mt-2 space-y-2 border-l border-border pl-2 md:ml-4 md:pl-4"
                      >
                        {orchestrator.subagents.map((agent) => (
                          <AgentNodeCard
                            key={agent.agent_id}
                            agent={agent}
                            expanded={expandedAgentId === agent.agent_id}
                            onToggle={toggleAgent}
                          />
                        ))}
                      </ul>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
