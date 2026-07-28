"use client";

/**
 * Knowledge Base browser page.
 *
 * Lists every namespace with its document count and token utilization.
 * Selecting a namespace loads its documents and renders the paginated
 * document table alongside ingestion pipeline status and retrieval
 * metrics.
 *
 * @module app/knowledge/page
 */

import * as React from "react";
import { Database } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DocumentList } from "@/components/knowledge/document-list";
import {
  IngestionStatus,
  documentsToIngestionRecords,
  type RetrievalMetrics,
} from "@/components/knowledge/ingestion-status";
import { getDocuments, getNamespaces } from "@/lib/api/knowledge";
import type { KBDocument, KBNamespace } from "@/types";

/** Upper bound on documents fetched per namespace for client-side paging. */
const DOCUMENT_FETCH_LIMIT = 500;

/**
 * Read optional retrieval metrics attached to a namespace payload.
 *
 * The metrics block is additive on the backend, so it is read
 * defensively and omitted when absent or malformed.
 */
function readRetrievalMetrics(
  namespace: KBNamespace | null,
): RetrievalMetrics | null {
  const raw = (namespace as unknown as { retrieval_metrics?: unknown } | null)
    ?.retrieval_metrics;
  if (typeof raw !== "object" || raw === null) return null;
  const candidate = raw as Record<string, unknown>;
  if (
    typeof candidate["avg_latency_ms"] !== "number" ||
    typeof candidate["query_count"] !== "number" ||
    typeof candidate["cache_hit_rate"] !== "number"
  ) {
    return null;
  }
  return {
    avg_latency_ms: candidate["avg_latency_ms"],
    query_count: candidate["query_count"],
    cache_hit_rate: candidate["cache_hit_rate"],
  };
}

/** Knowledge Base namespace browser with document management. */
export default function KnowledgePage() {
  const [namespaces, setNamespaces] = React.useState<KBNamespace[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [documents, setDocuments] = React.useState<KBDocument[]>([]);
  const [isLoadingNamespaces, setIsLoadingNamespaces] = React.useState(true);
  const [isLoadingDocuments, setIsLoadingDocuments] = React.useState(false);
  const [namespaceError, setNamespaceError] = React.useState<string | null>(
    null,
  );
  const [documentError, setDocumentError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setIsLoadingNamespaces(true);
    setNamespaceError(null);

    getNamespaces()
      .then((items) => {
        if (cancelled) return;
        setNamespaces(items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setNamespaceError(
          err instanceof Error ? err.message : "Failed to load namespaces",
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoadingNamespaces(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  React.useEffect(() => {
    if (!selected) {
      setDocuments([]);
      return;
    }

    let cancelled = false;
    setIsLoadingDocuments(true);
    setDocumentError(null);

    getDocuments(selected, { offset: 0, limit: DOCUMENT_FETCH_LIMIT })
      .then((response) => {
        if (cancelled) return;
        setDocuments(response.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setDocumentError(
          err instanceof Error ? err.message : "Failed to load documents",
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoadingDocuments(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selected]);

  const selectedNamespace = React.useMemo(
    () => namespaces.find((entry) => entry.namespace === selected) ?? null,
    [namespaces, selected],
  );

  const metrics = React.useMemo(
    () => readRetrievalMetrics(selectedNamespace),
    [selectedNamespace],
  );

  const uploads = React.useMemo(
    () => documentsToIngestionRecords(documents),
    [documents],
  );

  /** Drop a deleted document locally and decrement namespace counters. */
  const handleDeleted = React.useCallback(
    (documentId: string) => {
      const removed =
        documents.find((document) => document.document_id === documentId) ??
        null;

      setDocuments((current) =>
        current.filter((document) => document.document_id !== documentId),
      );

      if (!removed) return;
      setNamespaces((entries) =>
        entries.map((entry) =>
          entry.namespace === removed.namespace
            ? {
                ...entry,
                document_count: Math.max(0, entry.document_count - 1),
                total_tokens: Math.max(
                  0,
                  entry.total_tokens - removed.total_tokens,
                ),
              }
            : entry,
        ),
      );
    },
    [documents],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">Knowledge base</h2>
          <p className="text-sm text-muted-foreground">
            Browse namespaces, inspect ingested documents, and remove outdated
            content.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setReloadKey((key) => key + 1)}
          disabled={isLoadingNamespaces}
          aria-label="Refresh namespaces"
          aria-busy={isLoadingNamespaces}
        >
          Refresh
        </Button>
      </div>

      {namespaceError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load namespaces: {namespaceError}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Retry
          </Button>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <section aria-label="Namespaces" className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Namespaces
          </h3>
          {isLoadingNamespaces ? (
            <div
              className="space-y-2"
              role="status"
              aria-busy="true"
              aria-label="Loading namespaces"
            >
              {Array.from({ length: 5 }).map((_, index) => (
                <Skeleton key={index} className="h-16 w-full" />
              ))}
            </div>
          ) : namespaces.length === 0 ? (
            <p className="rounded-lg border border-border px-3 py-6 text-center text-sm text-muted-foreground">
              No namespaces available.
            </p>
          ) : (
            <ul className="space-y-2">
              {namespaces.map((entry) => {
                const isSelected = entry.namespace === selected;
                return (
                  <li key={entry.namespace}>
                    {/*
                      Single-select list, so the chosen namespace is marked
                      with `aria-current` rather than `aria-pressed`; using
                      both would make screen readers announce the selection
                      state twice.
                    */}
                    <button
                      type="button"
                      onClick={() => setSelected(entry.namespace)}
                      aria-current={isSelected ? "true" : undefined}
                      aria-label={`${entry.namespace} namespace, ${entry.document_count.toLocaleString()} documents, ${entry.total_tokens.toLocaleString()} tokens`}
                      className={cn(
                        "min-h-touch w-full rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        isSelected
                          ? "border-primary bg-accent"
                          : "border-input hover:bg-accent/60",
                      )}
                    >
                      <span className="flex items-center gap-2">
                        <Database
                          className="h-4 w-4 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                        <span className="truncate font-medium">
                          {entry.namespace}
                        </span>
                      </span>
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {entry.document_count.toLocaleString()} docs ·{" "}
                        {entry.total_tokens.toLocaleString()} tokens
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section aria-label="Documents" className="space-y-6">
          {!selected ? (
            <p className="rounded-lg border border-border px-4 py-12 text-center text-sm text-muted-foreground">
              Select a namespace to browse its documents.
            </p>
          ) : documentError ? (
            <div
              role="alert"
              className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
            >
              Could not load documents: {documentError}
            </div>
          ) : isLoadingDocuments ? (
            <div
              className="space-y-3"
              role="status"
              aria-busy="true"
              aria-label="Loading documents"
            >
              <Skeleton className="h-10 w-full" />
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : (
            <>
              <DocumentList
                namespace={selected}
                documents={documents}
                onDeleted={handleDeleted}
              />
              <IngestionStatus uploads={uploads} metrics={metrics} />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
