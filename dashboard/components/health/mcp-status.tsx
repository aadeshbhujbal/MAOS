"use client";

/**
 * MCP server status table.
 *
 * Lists every registered MCP server with its endpoint, health badge,
 * measured latency, and consecutive failure count. Servers with one or
 * more consecutive failures are highlighted and annotated with the
 * timestamp of the failing health check.
 *
 * Optionally renders LLM provider status (including rate limit
 * proximity) when the backend supplies it.
 *
 * @module components/health/mcp-status
 */

import * as React from "react";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatTimestamp } from "@/lib/utils/format";
import type { MCPServerStatus } from "@/types";

/** Health status shared by MAOS services, MCP servers, and providers. */
export type HealthStatus = "healthy" | "degraded" | "unavailable";

/**
 * Tailwind classes per health status.
 *
 * healthy = green, degraded = yellow, unavailable = red. The status word is
 * always rendered as badge text, so health is never conveyed by color alone
 * (SC 1.4.1), and each text shade clears 4.5:1 on its tinted background
 * (SC 1.4.3).
 */
export const HEALTH_BADGE_CLASSES: Record<HealthStatus, string> = {
  healthy:
    "bg-green-500/15 text-green-800 dark:text-green-300 border-green-500/40",
  degraded:
    "bg-yellow-500/15 text-yellow-800 dark:text-yellow-300 border-yellow-500/40",
  unavailable: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40",
};

/**
 * Resolve the badge class for a health status, falling back to a neutral
 * style for values the backend may introduce later.
 *
 * @param status - Health status value from the API.
 * @returns Tailwind class string for the badge.
 */
export function healthBadgeClass(status: HealthStatus | string): string {
  return (
    HEALTH_BADGE_CLASSES[status as HealthStatus] ??
    "bg-muted text-muted-foreground border-border"
  );
}

/** Props for {@link HealthBadge}. */
export interface HealthBadgeProps {
  /** Health status to display. */
  status: HealthStatus | string;
  /** Extra classes appended to the badge. */
  className?: string;
}

/** Color-coded health status badge. */
export function HealthBadge({ status, className }: HealthBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={cn("whitespace-nowrap", healthBadgeClass(status), className)}
    >
      {String(status)}
    </Badge>
  );
}

/** Format a latency measurement for table display. */
function formatLatency(latencyMs?: number): string {
  if (typeof latencyMs !== "number" || Number.isNaN(latencyMs)) return "—";
  return `${Math.round(latencyMs)} ms`;
}

/**
 * Status of an LLM provider as reported by the health subsystem.
 *
 * Rate limit proximity is a 0-1 ratio of the current request/token rate
 * against the provider quota.
 */
export interface LLMProviderStatus {
  /** Provider name (e.g., Anthropic, OpenAI, Bedrock, Vertex). */
  provider: string;
  /** Current health status. */
  status: HealthStatus;
  /** Proximity to the provider rate limit, 0-1. */
  rate_limit_proximity?: number;
  /** Number of context handoffs currently in flight. */
  active_context_handoffs?: number;
}

/** Props for {@link MCPStatus}. */
export interface MCPStatusProps {
  /** Registered MCP servers to display. */
  servers: MCPServerStatus[];
  /** LLM provider status rows, when available. */
  providers?: LLMProviderStatus[];
  /** Extra classes for the outer container. */
  className?: string;
}

/** Column labels for the MCP server table. */
const COLUMNS = [
  "Server",
  "Endpoint",
  "Status",
  "Latency",
  "Consecutive failures",
  "Last check",
];

/**
 * Table of registered MCP servers with health, latency, and failure data.
 *
 * @example
 * ```tsx
 * <MCPStatus servers={servers} />
 * ```
 */
export function MCPStatus({ servers, providers, className }: MCPStatusProps) {
  return (
    <section
      className={cn("space-y-4", className)}
      aria-label="MCP servers"
      aria-live="polite"
      aria-atomic="false"
    >
      <div className="rounded-lg border border-border">
        <Table>
          <caption className="sr-only">
            Registered MCP servers with health status, latency, and consecutive
            failure counts
          </caption>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {COLUMNS.map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {servers.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <td
                  colSpan={COLUMNS.length}
                  className="px-3 py-10 text-center text-sm text-muted-foreground"
                >
                  No MCP servers registered.
                </td>
              </TableRow>
            ) : (
              servers.map((server) => {
                const isFailing = server.consecutive_failures > 0;
                return (
                  <TableRow
                    key={`${server.name}:${server.endpoint}`}
                    className={cn(
                      isFailing && "bg-red-500/10 hover:bg-red-500/15",
                    )}
                  >
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        {isFailing ? (
                          <AlertTriangle
                            className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
                            role="img"
                            aria-label="Failing health checks"
                          />
                        ) : null}
                        <span>{server.name}</span>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {server.endpoint}
                    </TableCell>
                    <TableCell>
                      <HealthBadge status={server.status} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {formatLatency(server.latency_ms)}
                    </TableCell>
                    <TableCell>
                      {isFailing ? (
                        <span className="text-xs font-medium text-red-700 dark:text-red-400">
                          {server.consecutive_failures} failed since{" "}
                          {formatTimestamp(server.last_check)}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">0</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatTimestamp(server.last_check)}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {providers && providers.length > 0 ? (
        <div className="rounded-lg border border-border">
          <Table>
            <caption className="sr-only">
              LLM provider status with rate limit proximity
            </caption>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Provider</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Rate limit proximity</TableHead>
                <TableHead>Context handoffs</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.map((provider) => {
                const proximity = provider.rate_limit_proximity;
                const nearLimit =
                  typeof proximity === "number" && proximity >= 0.8;
                return (
                  <TableRow key={provider.provider}>
                    <TableCell className="font-medium">
                      {provider.provider}
                    </TableCell>
                    <TableCell>
                      <HealthBadge status={provider.status} />
                    </TableCell>
                    <TableCell
                      className={cn(
                        "whitespace-nowrap text-xs",
                        nearLimit &&
                          "font-medium text-yellow-800 dark:text-yellow-300",
                      )}
                    >
                      {typeof proximity === "number"
                        ? `${Math.round(proximity * 100)}%`
                        : "—"}
                      {nearLimit ? (
                        <span className="sr-only"> — near rate limit</span>
                      ) : null}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {provider.active_context_handoffs ?? 0}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </section>
  );
}
