"use client";

/**
 * Knowledge Base ingestion pipeline status and retrieval metrics.
 *
 * Lists recent uploads with a processing-state badge (queued, processing,
 * completed, failed) and summarises per-namespace retrieval performance:
 * average latency, query count, and cache hit rate.
 *
 * @module components/knowledge/ingestion-status
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatTimestamp } from "@/lib/utils/format";
import type { KBDocument } from "@/types";

/** Processing state of an ingestion pipeline record. */
export type IngestionState = "queued" | "processing" | "completed" | "failed";

/** Tailwind classes per ingestion state. */
export const INGESTION_BADGE_CLASSES: Record<IngestionState, string> = {
  queued: "bg-gray-500/15 text-gray-700 dark:text-gray-300 border-gray-500/40",
  processing:
    "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/40",
  completed:
    "bg-green-500/15 text-green-800 dark:text-green-300 border-green-500/40",
  failed: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40",
};

/** Valid ingestion state values, used for narrowing API payloads. */
const INGESTION_STATES: IngestionState[] = [
  "queued",
  "processing",
  "completed",
  "failed",
];

/** One entry in the ingestion pipeline feed. */
export interface IngestionRecord {
  /** Document identifier. */
  document_id: string;
  /** Original filename. */
  filename: string;
  /** Current processing state. */
  state: IngestionState;
  /** ISO 8601 upload timestamp. */
  uploaded_at: string;
  /** Chunks produced so far, when known. */
  chunk_count?: number;
}

/** Retrieval performance metrics for a namespace. */
export interface RetrievalMetrics {
  /** Average retrieval latency in milliseconds. */
  avg_latency_ms: number;
  /** Number of retrieval queries recorded. */
  query_count: number;
  /** Cache hit rate as a 0-1 ratio. */
  cache_hit_rate: number;
}

/**
 * Map Knowledge Base documents into ingestion records.
 *
 * A document present in the KB has finished ingesting, so it maps to
 * `completed` unless the backend attaches an explicit state.
 *
 * @param documents - Documents for the selected namespace.
 * @param limit - Maximum number of recent records to return.
 * @returns Ingestion records sorted newest-first.
 */
export function documentsToIngestionRecords(
  documents: KBDocument[],
  limit = 5,
): IngestionRecord[] {
  return [...documents]
    .sort(
      (a, b) =>
        new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
    )
    .slice(0, Math.max(0, limit))
    .map((document) => {
      const raw = (document as unknown as Record<string, unknown>)[
        "ingestion_state"
      ];
      const state = INGESTION_STATES.includes(raw as IngestionState)
        ? (raw as IngestionState)
        : "completed";
      return {
        document_id: document.document_id,
        filename: document.filename,
        state,
        uploaded_at: document.uploaded_at,
        chunk_count: document.chunk_count,
      };
    });
}

/** Props for {@link IngestionStatus}. */
export interface IngestionStatusProps {
  /** Recent uploads with their processing state. */
  uploads: IngestionRecord[];
  /** Retrieval metrics for the selected namespace, when available. */
  metrics?: RetrievalMetrics | null;
  /** Extra classes for the grid container. */
  className?: string;
}

/** Format a 0-1 ratio as a percentage. */
function formatRate(ratio: number | undefined): string {
  if (typeof ratio !== "number" || Number.isNaN(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}

/** Format a latency measurement. */
function formatLatency(latencyMs: number | undefined): string {
  if (typeof latencyMs !== "number" || Number.isNaN(latencyMs)) return "—";
  return `${Math.round(latencyMs)} ms`;
}

/**
 * Ingestion pipeline feed plus retrieval metrics cards.
 *
 * @example
 * ```tsx
 * <IngestionStatus uploads={uploads} metrics={metrics} />
 * ```
 */
export function IngestionStatus({
  uploads,
  metrics,
  className,
}: IngestionStatusProps) {
  return (
    <section
      aria-label="Ingestion status and retrieval metrics"
      className={cn("grid gap-4 lg:grid-cols-2", className)}
    >
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Recent uploads</CardTitle>
          <CardDescription className="text-xs">
            Ingestion pipeline state for the latest documents
          </CardDescription>
        </CardHeader>
        <CardContent>
          {uploads.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No recent uploads for this namespace.
            </p>
          ) : (
            <ul className="space-y-2">
              {uploads.map((upload) => (
                <li
                  key={upload.document_id}
                  className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {upload.filename}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatTimestamp(upload.uploaded_at)}
                      {typeof upload.chunk_count === "number"
                        ? ` · ${upload.chunk_count.toLocaleString()} chunks`
                        : ""}
                    </p>
                  </div>
                  <Badge
                    variant="outline"
                    className={cn(
                      "whitespace-nowrap",
                      INGESTION_BADGE_CLASSES[upload.state],
                    )}
                  >
                    <span className="sr-only">Ingestion state: </span>
                    {upload.state}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">
            Retrieval metrics
          </CardTitle>
          <CardDescription className="text-xs">
            Per-namespace query performance
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-3 gap-4">
            <div>
              <dt className="text-xs text-muted-foreground">Avg latency</dt>
              <dd className="text-xl font-semibold tabular-nums">
                {formatLatency(metrics?.avg_latency_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Queries</dt>
              <dd className="text-xl font-semibold tabular-nums">
                {typeof metrics?.query_count === "number"
                  ? metrics.query_count.toLocaleString()
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Cache hit rate</dt>
              <dd className="text-xl font-semibold tabular-nums">
                {formatRate(metrics?.cache_hit_rate)}
              </dd>
            </div>
          </dl>
          {!metrics ? (
            <p className="mt-3 text-xs text-muted-foreground">
              Retrieval metrics are not being reported for this namespace.
            </p>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}
