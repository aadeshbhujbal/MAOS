"use client";

/**
 * Token consumption trend chart.
 *
 * Renders a Recharts line chart of token consumption over time with one
 * line per LLM provider (Anthropic, OpenAI, Bedrock, Vertex, plus any
 * additional providers present in the data). Series are downsampled to a
 * maximum of 500 points to keep rendering at interactive frame rates.
 *
 * @module components/costs/cost-chart
 */

import * as React from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "@/lib/utils";
import type { CostRecord } from "@/types";

/** Maximum number of rendered points per series. */
export const MAX_CHART_POINTS = 500;

/** Providers always shown in the legend when present in the data. */
export const KNOWN_PROVIDERS = [
  "Anthropic",
  "OpenAI",
  "Bedrock",
  "Vertex",
] as const;

/** Stable line colors for the known providers. */
const PROVIDER_COLORS: Record<string, string> = {
  Anthropic: "#d97757",
  OpenAI: "#10a37f",
  Bedrock: "#ff9900",
  Vertex: "#4285f4",
};

/** Fallback palette for providers not in the known list. */
const FALLBACK_COLORS = ["#8b5cf6", "#ec4899", "#14b8a6", "#f59e0b", "#64748b"];

/**
 * A single chart row: a timestamp bucket plus per-provider token totals.
 *
 * Provider keys are dynamic, so the shape carries an index signature.
 */
export interface CostChartPoint {
  /** Epoch milliseconds of the bucket, used for ordering. */
  ts: number;
  /** Formatted axis label for the bucket. */
  label: string;
  /** Token totals keyed by provider name. */
  [provider: string]: number | string;
}

/** Props accepted by the CostChart component. */
export interface CostChartProps {
  /** Cost records to plot. Order does not matter; they are sorted internally. */
  records: CostRecord[];
  /** Maximum points rendered per series. Defaults to 500. */
  maxPoints?: number;
  /** Chart height in pixels. Defaults to 320. */
  height?: number;
  /** Additional classes for the chart wrapper. */
  className?: string;
}

/**
 * Reduce a series to at most `maxPoints` entries using an even stride.
 *
 * The first and last points are always preserved so the visible time span
 * matches the underlying data.
 *
 * @param points - Ordered series points.
 * @param maxPoints - Maximum number of points to keep (minimum 1).
 * @returns A new array with at most `maxPoints` entries.
 */
export function downsamplePoints<T>(
  points: T[],
  maxPoints: number = MAX_CHART_POINTS,
): T[] {
  const limit = Math.max(1, Math.floor(maxPoints));
  if (points.length <= limit) return [...points];

  const stride = points.length / limit;
  const sampled: T[] = [];
  for (let i = 0; i < limit; i += 1) {
    sampled.push(points[Math.floor(i * stride)]!);
  }

  // Always keep the final point so the range end is accurate.
  const last = points[points.length - 1]!;
  if (sampled[sampled.length - 1] !== last) {
    sampled[sampled.length - 1] = last;
  }
  return sampled;
}

/**
 * Bucket cost records by timestamp and sum tokens per provider.
 *
 * @param records - Raw cost records.
 * @returns Chronologically ordered chart points.
 */
export function buildCostSeries(records: CostRecord[]): CostChartPoint[] {
  const buckets = new Map<number, CostChartPoint>();

  for (const record of records) {
    const ts = new Date(record.timestamp).getTime();
    if (Number.isNaN(ts)) continue;

    let point = buckets.get(ts);
    if (!point) {
      point = {
        ts,
        label: new Date(ts).toLocaleTimeString(undefined, {
          hour: "2-digit",
          minute: "2-digit",
        }),
      };
      buckets.set(ts, point);
    }

    const provider = record.provider || "unknown";
    const current = point[provider];
    point[provider] =
      (typeof current === "number" ? current : 0) + record.tokens;
  }

  return Array.from(buckets.values()).sort((a, b) => a.ts - b.ts);
}

/**
 * Collect the provider names present in the records, known providers first.
 *
 * @param records - Raw cost records.
 * @returns Ordered provider names for line series.
 */
export function listProviders(records: CostRecord[]): string[] {
  const present = new Set(
    records.map((record) => record.provider || "unknown"),
  );
  const known = KNOWN_PROVIDERS.filter((provider) => present.has(provider));
  const knownNames: readonly string[] = KNOWN_PROVIDERS;
  const extra = Array.from(present)
    .filter((provider) => !knownNames.includes(provider))
    .sort();
  return [...known, ...extra];
}

/** Resolve a stable color for a provider line. */
function providerColor(provider: string, index: number): string {
  return (
    PROVIDER_COLORS[provider] ??
    FALLBACK_COLORS[index % FALLBACK_COLORS.length]!
  );
}

/**
 * Line chart of token consumption over time, broken down by provider.
 *
 * @example
 * ```tsx
 * <CostChart records={costRecords} />
 * ```
 */
export function CostChart({
  records,
  maxPoints = MAX_CHART_POINTS,
  height = 320,
  className,
}: CostChartProps) {
  const providers = React.useMemo(() => listProviders(records), [records]);
  const data = React.useMemo(
    () => downsamplePoints(buildCostSeries(records), maxPoints),
    [records, maxPoints],
  );

  if (data.length === 0) {
    return (
      <div
        className={cn(
          "flex items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground",
          className,
        )}
        style={{ height }}
      >
        No token consumption recorded for this range.
      </div>
    );
  }

  return (
    <div
      className={cn("w-full", className)}
      style={{ height }}
      role="img"
      aria-label={`Token consumption over time across ${providers.length} providers`}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="currentColor"
            opacity={0.15}
          />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11 }}
            stroke="currentColor"
            opacity={0.6}
            minTickGap={24}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            stroke="currentColor"
            opacity={0.6}
            width={64}
            tickFormatter={(value: unknown) => Number(value).toLocaleString()}
          />
          <Tooltip
            formatter={(value: unknown) =>
              `${Number(value).toLocaleString()} tokens`
            }
          />
          <Legend />
          {providers.map((provider, index) => (
            <Line
              key={provider}
              type="monotone"
              dataKey={provider}
              name={provider}
              stroke={providerColor(provider, index)}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
