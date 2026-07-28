"use client";

/**
 * System metrics panel.
 *
 * Renders three cards summarising live throughput signals: active
 * WebSocket connections, message queue depth, and task processing rate
 * in tasks per minute.
 *
 * @module components/health/metrics-panel
 */

import * as React from "react";
import { Activity, Layers, Plug } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/** Metrics snapshot reported by the health endpoint. */
export interface SystemMetrics {
  /** Number of active WebSocket connections. */
  active_ws_connections: number;
  /** Current message queue depth. */
  message_queue_depth: number;
  /** Tasks processed per minute (rolling average). */
  tasks_per_minute: number;
}

/** Props for {@link MetricsPanel}. */
export interface MetricsPanelProps {
  /** Metrics to display, or null while unavailable. */
  metrics: SystemMetrics | null;
  /** Extra classes for the grid container. */
  className?: string;
}

/** Format a numeric metric, tolerating missing values. */
function formatMetric(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(1);
}

/** Card definitions rendered by the panel. */
const METRIC_CARDS: {
  key: keyof SystemMetrics;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    key: "active_ws_connections",
    label: "WebSocket connections",
    description: "Active dashboard streams",
    icon: Plug,
  },
  {
    key: "message_queue_depth",
    label: "Queue depth",
    description: "Messages awaiting processing",
    icon: Layers,
  },
  {
    key: "tasks_per_minute",
    label: "Tasks / minute",
    description: "Rolling processing rate",
    icon: Activity,
  },
];

/**
 * Grid of system metric cards.
 *
 * @example
 * ```tsx
 * <MetricsPanel metrics={health.metrics} />
 * ```
 */
export function MetricsPanel({ metrics, className }: MetricsPanelProps) {
  return (
    <section
      aria-label="System metrics"
      aria-live="polite"
      aria-atomic="false"
      className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-3", className)}
    >
      {METRIC_CARDS.map((card) => {
        const Icon = card.icon;
        return (
          <Card key={card.key}>
            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
              <div className="space-y-1">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {card.label}
                </CardTitle>
                <CardDescription className="text-xs">
                  {card.description}
                </CardDescription>
              </div>
              <Icon
                className="h-4 w-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold tabular-nums">
                {formatMetric(metrics?.[card.key])}
              </p>
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}
