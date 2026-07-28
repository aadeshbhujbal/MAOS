"use client";

/**
 * System health monitoring page.
 *
 * Fetches service health, system metrics, and the MCP server registry over
 * REST, refreshes every 10 seconds (plus a manual refresh button), and
 * applies live `health.*` WebSocket events between polls.
 *
 * @module app/health/page
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  HealthBadge,
  MCPStatus,
  type LLMProviderStatus,
} from "@/components/health/mcp-status";
import {
  MetricsPanel,
  type SystemMetrics,
} from "@/components/health/metrics-panel";
import { getAuthToken } from "@/lib/api/client";
import {
  getHealthStatus,
  getMCPServers,
  type HealthStatusResponse,
} from "@/lib/api/health";
import { TOPICS } from "@/lib/ws/subscriptions";
import { useWebSocket } from "@/hooks/use-websocket";
import { formatTimestamp } from "@/lib/utils/format";
import type { MCPServerStatus, ServiceHealth, WSEvent } from "@/types";

/** Auto-refresh cadence for the health panel (Requirement 5.6). */
const REFRESH_INTERVAL_MS = 10_000;

/** Services MAOS always reports on, in display order. */
const EXPECTED_SERVICES = [
  "API workers",
  "Arq workers",
  "Postgres",
  "Redis",
  "Neo4j",
] as const;

/** Normalize a service name for matching backend variants. */
function normalizeName(name: string): string {
  return name.toLowerCase().replace(/[\s_-]+/g, "");
}

/**
 * Merge reported services with the expected set so a missing service is
 * shown as unavailable rather than silently dropped.
 */
function mergeServices(reported: ServiceHealth[]): ServiceHealth[] {
  const byName = new Map(
    reported.map((service) => [normalizeName(service.service), service]),
  );

  const merged: ServiceHealth[] = EXPECTED_SERVICES.map((expected) => {
    const match = byName.get(normalizeName(expected));
    byName.delete(normalizeName(expected));
    return (
      match ?? {
        service: expected,
        status: "unavailable",
        last_check: "",
      }
    );
  });

  // Preserve any additional services the backend reports.
  return [...merged, ...byName.values()];
}

/** Format a latency measurement for the service grid. */
function formatLatency(latencyMs?: number): string {
  if (typeof latencyMs !== "number" || Number.isNaN(latencyMs)) return "—";
  return `${Math.round(latencyMs)} ms`;
}

/** Read a `health.*` payload as a service health update. */
function readServicePayload(
  payload: Record<string, unknown>,
): ServiceHealth | null {
  const service = payload["service"];
  const status = payload["status"];
  if (typeof service !== "string" || typeof status !== "string") return null;
  return payload as unknown as ServiceHealth;
}

/** Read a `health.*` payload as an MCP server status update. */
function readServerPayload(
  payload: Record<string, unknown>,
): MCPServerStatus | null {
  const name = payload["name"];
  const endpoint = payload["endpoint"];
  if (typeof name !== "string" || typeof endpoint !== "string") return null;
  return payload as unknown as MCPServerStatus;
}

/** Read a `health.*` payload as a system metrics snapshot. */
function readMetricsPayload(
  payload: Record<string, unknown>,
): SystemMetrics | null {
  const source =
    typeof payload["metrics"] === "object" && payload["metrics"] !== null
      ? (payload["metrics"] as Record<string, unknown>)
      : payload;
  const connections = source["active_ws_connections"];
  const depth = source["message_queue_depth"];
  const rate = source["tasks_per_minute"];
  if (
    typeof connections !== "number" ||
    typeof depth !== "number" ||
    typeof rate !== "number"
  ) {
    return null;
  }
  return {
    active_ws_connections: connections,
    message_queue_depth: depth,
    tasks_per_minute: rate,
  };
}

/**
 * Read optional LLM provider status rows from the health response.
 *
 * The provider block is additive on the backend, so it is read
 * defensively and omitted when absent or malformed.
 */
function readProviders(
  response: HealthStatusResponse | null,
): LLMProviderStatus[] {
  const raw = (response as unknown as { providers?: unknown } | null)
    ?.providers;
  if (!Array.isArray(raw)) return [];
  return raw.filter((entry): entry is LLMProviderStatus => {
    if (typeof entry !== "object" || entry === null) return false;
    const candidate = entry as Record<string, unknown>;
    return (
      typeof candidate["provider"] === "string" &&
      typeof candidate["status"] === "string"
    );
  });
}

/** Loading placeholder for the service grid. */
function ServiceGridSkeleton() {
  return (
    <div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      role="status"
      aria-busy="true"
      aria-label="Loading service health"
    >
      {Array.from({ length: EXPECTED_SERVICES.length }).map((_, index) => (
        <Skeleton key={index} className="h-28 w-full" />
      ))}
    </div>
  );
}

/** Health dashboard with polling plus live streaming updates. */
export default function HealthPage() {
  const [health, setHealth] = React.useState<HealthStatusResponse | null>(null);
  const [servers, setServers] = React.useState<MCPServerStatus[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = React.useState<string | null>(null);
  const [token, setToken] = React.useState("");

  // The auth cookie is only readable on the client.
  React.useEffect(() => {
    setToken(getAuthToken());
  }, []);

  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = React.useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [healthStatus, mcpServers] = await Promise.all([
        getHealthStatus(),
        getMCPServers(),
      ]);
      if (!mountedRef.current) return;
      setHealth(healthStatus);
      setServers(mcpServers);
      setError(null);
      setLastRefreshed(new Date().toISOString());
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setError(
        err instanceof Error ? err.message : "Failed to load health status",
      );
    } finally {
      if (mountedRef.current) {
        setIsRefreshing(false);
        setIsLoading(false);
      }
    }
  }, []);

  // Initial fetch plus 10-second auto-refresh.
  React.useEffect(() => {
    void load();
    const interval = setInterval(() => {
      void load();
    }, REFRESH_INTERVAL_MS);
    return () => {
      clearInterval(interval);
    };
  }, [load]);

  const handleEvent = React.useCallback((event: WSEvent) => {
    if (!event.topic.startsWith("health.")) return;

    const server = readServerPayload(event.payload);
    if (server) {
      setServers((current) => {
        const index = current.findIndex((entry) => entry.name === server.name);
        if (index === -1) return [...current, server];
        const next = [...current];
        next[index] = { ...next[index], ...server };
        return next;
      });
      return;
    }

    const service = readServicePayload(event.payload);
    if (service) {
      setHealth((current) => {
        if (!current) return current;
        const index = current.services.findIndex(
          (entry) =>
            normalizeName(entry.service) === normalizeName(service.service),
        );
        const services =
          index === -1
            ? [...current.services, service]
            : current.services.map((entry, i) =>
                i === index ? { ...entry, ...service } : entry,
              );
        return { ...current, services };
      });
      return;
    }

    const metrics = readMetricsPayload(event.payload);
    if (metrics) {
      setHealth((current) => (current ? { ...current, metrics } : current));
    }
  }, []);

  useWebSocket({
    token,
    topics: [TOPICS.HEALTH],
    onEvent: handleEvent,
  });

  const services = React.useMemo(
    () => mergeServices(health?.services ?? []),
    [health],
  );

  const providers = React.useMemo(() => readProviders(health), [health]);

  const healthyCount = React.useMemo(
    () => services.filter((service) => service.status === "healthy").length,
    [services],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">Health</h2>
          {/*
            Deliberately not a live region: the refresh stamp changes every
            10 seconds, and announcing it would flood a screen reader. The
            polite announcement below is keyed to the overall status instead,
            so it only speaks when health actually changes (Requirement 9.2).
          */}
          <p className="text-sm text-muted-foreground" aria-busy={isRefreshing}>
            Service health, MCP connectivity, and throughput. Auto-refreshes
            every 10 seconds
            {lastRefreshed
              ? ` — last updated ${formatTimestamp(lastRefreshed)}`
              : ""}
            .
          </p>
          <p
            role="status"
            aria-live="polite"
            aria-atomic="true"
            className="sr-only"
          >
            {health
              ? `Overall system health: ${health.overall}. ${healthyCount} of ${services.length} services healthy.`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {health ? (
            <span className="flex items-center gap-1">
              <span className="sr-only">Overall system health:</span>
              <HealthBadge status={health.overall} />
            </span>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={isRefreshing}
            aria-label="Refresh health status now"
            aria-busy={isRefreshing}
          >
            Refresh
          </Button>
        </div>
      </div>

      {error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load health status: {error}</span>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Retry
          </Button>
        </div>
      ) : null}

      {isLoading ? (
        <ServiceGridSkeleton />
      ) : (
        <section
          aria-label="Service health"
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        >
          {services.map((service) => (
            <Card key={service.service}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">
                  {service.service}
                </CardTitle>
                <span className="flex items-center">
                  <span className="sr-only">Status:</span>
                  <HealthBadge status={service.status} />
                </span>
              </CardHeader>
              <CardContent className="space-y-1 text-xs text-muted-foreground">
                <p>Latency: {formatLatency(service.latency_ms)}</p>
                <p>Last check: {formatTimestamp(service.last_check)}</p>
              </CardContent>
            </Card>
          ))}
        </section>
      )}

      <div className="space-y-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          System metrics
        </h3>
        <MetricsPanel metrics={health?.metrics ?? null} />
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          MCP servers
        </h3>
        {isLoading ? (
          <div role="status" aria-busy="true" aria-label="Loading MCP servers">
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <MCPStatus servers={servers} providers={providers} />
        )}
      </div>
    </div>
  );
}
