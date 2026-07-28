"use client";

/**
 * Audit log page.
 *
 * Fetches audit entries over REST (the backend scopes results to the
 * authenticated tenant), then applies event-type chips, a time-range filter,
 * free-text search, and offset pagination using the shared pure utilities.
 * New entries stream in over the `audit.*` WebSocket topic, and the current
 * filtered view can be exported to CSV.
 *
 * @module app/audit/page
 */

import * as React from "react";
import { Download, Search } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AuditDetail, isSecurityEvent } from "@/components/audit/audit-detail";
import { getAuditLog } from "@/lib/api/audit";
import { getAuthToken } from "@/lib/api/client";
import { auditEntriesToCSV } from "@/lib/utils/csv-export";
import { filterAuditEntries, filterByTimeRange } from "@/lib/utils/filters";
import { formatTimestamp } from "@/lib/utils/format";
import { paginate } from "@/lib/utils/pagination";
import { TOPICS } from "@/lib/ws/subscriptions";
import { useWebSocket } from "@/hooks/use-websocket";
import type { AuditEntry, AuditEventType, WSEvent } from "@/types";

/** Maximum entries pulled from the API in one page fetch. */
const FETCH_LIMIT = 500;

/** Rows shown per page in the table. */
const PAGE_SIZE = 25;

/** All selectable event types, ordered for the filter chip row. */
const EVENT_TYPES: AuditEventType[] = [
  "routing_decision",
  "tool_invocation",
  "approval_request",
  "approval_decision",
  "delegation",
  "error",
  "access_denial",
  "phi_redaction",
  "sandbox_violation",
];

/** Convert an ISO timestamp to the `datetime-local` input format. */
function toLocalInputValue(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Parse a `datetime-local` value into an ISO string, or null when invalid. */
function toIso(localValue: string): string | null {
  if (!localValue) return null;
  const date = new Date(localValue);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Narrow a WebSocket payload into an AuditEntry when it carries an entry_id. */
function readAuditPayload(payload: Record<string, unknown>): AuditEntry | null {
  const entryId = payload["entry_id"];
  if (typeof entryId !== "string" || !entryId) return null;
  return payload as unknown as AuditEntry;
}

/** Trigger a client-side download of the given CSV text. */
function downloadCsv(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** Loading placeholder mirroring the audit table layout. */
function AuditSkeleton() {
  return (
    <div
      className="space-y-3"
      role="status"
      aria-busy="true"
      aria-label="Loading audit log"
    >
      <Skeleton className="h-10 w-full" />
      {Array.from({ length: 8 }).map((_, index) => (
        <Skeleton key={index} className="h-12 w-full" />
      ))}
    </div>
  );
}

/** Audit log page with filtering, detail modal, and CSV export. */
export default function AuditPage() {
  const [entries, setEntries] = React.useState<AuditEntry[]>([]);
  const [selectedTypes, setSelectedTypes] = React.useState<AuditEventType[]>(
    [],
  );
  const [search, setSearch] = React.useState("");
  const [startInput, setStartInput] = React.useState("");
  const [endInput, setEndInput] = React.useState(() =>
    toLocalInputValue(new Date().toISOString()),
  );
  const [page, setPage] = React.useState(0);
  const [selected, setSelected] = React.useState<AuditEntry | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [token, setToken] = React.useState("");

  // The auth cookie is only readable on the client.
  React.useEffect(() => {
    setToken(getAuthToken());
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    getAuditLog(undefined, { offset: 0, limit: FETCH_LIMIT })
      .then((response) => {
        if (cancelled) return;
        setEntries(response.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load audit log",
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const handleEvent = React.useCallback((event: WSEvent) => {
    if (!event.topic.startsWith("audit.")) return;
    const entry = readAuditPayload(event.payload);
    if (!entry) return;
    setEntries((current) =>
      current.some((e) => e.entry_id === entry.entry_id)
        ? current
        : [entry, ...current],
    );
  }, []);

  useWebSocket({
    token,
    topics: [TOPICS.AUDIT],
    onEvent: handleEvent,
  });

  const toggleType = React.useCallback((eventType: AuditEventType) => {
    setPage(0);
    setSelectedTypes((current) =>
      current.includes(eventType)
        ? current.filter((t) => t !== eventType)
        : [...current, eventType],
    );
  }, []);

  /** Entries after event-type, time-range, and search filtering. */
  const filtered = React.useMemo(() => {
    let result = filterAuditEntries(entries, selectedTypes);

    const startIso = toIso(startInput);
    const endIso = toIso(endInput);
    if (startIso || endIso) {
      result = filterByTimeRange(
        result,
        startIso ?? new Date(0).toISOString(),
        endIso ?? new Date(8640000000000000).toISOString(),
      );
    }

    const query = search.trim().toLowerCase();
    if (query) {
      result = result.filter((entry) =>
        [entry.summary, entry.event_type, entry.task_id, entry.agent_id ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(query),
      );
    }

    return result;
  }, [entries, selectedTypes, startInput, endInput, search]);

  const pageData = React.useMemo(
    () => paginate(filtered, { offset: page * PAGE_SIZE, limit: PAGE_SIZE }),
    [filtered, page],
  );

  const totalPages = Math.max(1, Math.ceil(pageData.total_count / PAGE_SIZE));

  // Keep the page in range when filters shrink the result set.
  React.useEffect(() => {
    if (page > 0 && page >= totalPages) setPage(totalPages - 1);
  }, [page, totalPages]);

  const handleExport = React.useCallback(() => {
    const csv = auditEntriesToCSV(filtered);
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    downloadCsv(csv, `maos-audit-${stamp}.csv`);
  }, [filtered]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">Audit log</h2>
          <p className="text-sm text-muted-foreground">
            Scoped to your authorized tenant. New entries stream in live.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={filtered.length === 0}
            aria-label={`Export ${filtered.length} filtered audit entries to CSV`}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Export CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
            disabled={isLoading}
            aria-label="Refresh audit log"
            aria-busy={isLoading}
          >
            Refresh
          </Button>
        </div>
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted-foreground sm:min-w-[14rem]">
            Search
            <span className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden="true"
              />
              <Input
                className="pl-9"
                placeholder="Summary, task, or agent"
                aria-label="Search audit entries"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(0);
                }}
              />
            </span>
          </label>

          {/*
            The accessible name starts with the visible label text so
            speech-input users can address the field by what they see
            (SC 2.5.3 Label in Name).
          */}
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            From
            <Input
              type="datetime-local"
              className="w-52"
              aria-label="From — time range start"
              value={startInput}
              onChange={(event) => {
                setStartInput(event.target.value);
                setPage(0);
              }}
            />
          </label>

          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            To
            <Input
              type="datetime-local"
              className="w-52"
              aria-label="To — time range end"
              value={endInput}
              onChange={(event) => {
                setEndInput(event.target.value);
                setPage(0);
              }}
            />
          </label>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-xs text-muted-foreground">Event types</legend>
          <div className="flex flex-wrap gap-2">
            {EVENT_TYPES.map((eventType) => {
              const active = selectedTypes.includes(eventType);
              return (
                <button
                  key={eventType}
                  type="button"
                  onClick={() => toggleType(eventType)}
                  aria-pressed={active}
                  className={cn(
                    "inline-flex min-h-touch items-center rounded-full border px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background md:min-h-0",
                    active
                      ? "border-transparent bg-primary text-primary-foreground"
                      : "border-input text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    isSecurityEvent(eventType) &&
                      !active &&
                      "border-destructive",
                  )}
                >
                  {eventType}
                </button>
              );
            })}
          </div>
        </fieldset>
      </div>

      {error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load audit log: {error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Retry
          </Button>
        </div>
      ) : isLoading ? (
        <AuditSkeleton />
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <caption className="sr-only">
              Audit entries with timestamp, event type, task, agent, and
              summary. Use the details button in a row to open the full entry.
            </caption>
            <TableHeader>
              <TableRow>
                <TableHead>Timestamp</TableHead>
                <TableHead>Event type</TableHead>
                <TableHead>Task</TableHead>
                <TableHead>Agent</TableHead>
                <TableHead>Summary</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pageData.items.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    No audit entries match the current filters.
                  </TableCell>
                </TableRow>
              ) : (
                pageData.items.map((entry) => {
                  const security = isSecurityEvent(entry.event_type);
                  return (
                    <TableRow
                      key={entry.entry_id}
                      onClick={() => setSelected(entry)}
                      className={cn(
                        "cursor-pointer [&>td]:py-3 md:[&>td]:py-2",
                        security &&
                          "border-l-2 border-l-destructive bg-destructive/5",
                      )}
                    >
                      <TableCell className="whitespace-nowrap text-xs">
                        {formatTimestamp(entry.timestamp)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={security ? "destructive" : "outline"}>
                          {entry.event_type}
                          {security ? (
                            <span className="sr-only">
                              {" "}
                              (security-relevant)
                            </span>
                          ) : null}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-[10rem] truncate font-mono text-xs">
                        {entry.task_id}
                      </TableCell>
                      <TableCell className="max-w-[10rem] truncate font-mono text-xs">
                        {entry.agent_id ?? "—"}
                      </TableCell>
                      <TableCell className="max-w-[24rem] truncate">
                        {entry.summary}
                      </TableCell>
                      <TableCell>
                        {/*
                          Real in-row button rather than a click handler on
                          <tr>: keeps the row keyboard reachable through the
                          normal Tab order and preserves table semantics
                          (Requirement 9.2).
                        */}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelected(entry);
                          }}
                          aria-label={`View details for ${entry.event_type} entry ${entry.entry_id}`}
                          aria-haspopup="dialog"
                        >
                          View
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>

          <nav
            aria-label="Audit log pagination"
            className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2 text-xs text-muted-foreground"
          >
            {/* Entries arrive over WebSocket, so the count is a live region. */}
            <span role="status" aria-live="polite" aria-atomic="true">
              {pageData.total_count === 0
                ? "0 entries"
                : `${pageData.offset + 1}–${Math.min(
                    pageData.offset + pageData.items.length,
                    pageData.total_count,
                  )} of ${pageData.total_count} entries`}
            </span>
            <span className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                disabled={page === 0}
                aria-label="Go to previous page of audit entries"
              >
                Previous
              </Button>
              <span aria-live="polite" aria-atomic="true">
                Page {page + 1} of {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setPage((current) => Math.min(totalPages - 1, current + 1))
                }
                disabled={page >= totalPages - 1}
                aria-label="Go to next page of audit entries"
              >
                Next
              </Button>
            </span>
          </nav>
        </div>
      )}

      <AuditDetail entry={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
