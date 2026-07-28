"use client";

/**
 * Audit entry detail modal.
 *
 * Renders every identifier attached to an audit entry plus the raw JSON
 * detail payload. Security-relevant events (access denials, PHI redaction,
 * sandbox violations) get a red border and an explicit warning label.
 *
 * @module components/audit/audit-detail
 */

import * as React from "react";
import { ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { formatTimestamp } from "@/lib/utils/format";
import type { AuditEntry, AuditEventType } from "@/types";

/** Event types treated as security-relevant. */
export const SECURITY_EVENT_TYPES: AuditEventType[] = [
  "access_denial",
  "phi_redaction",
  "sandbox_violation",
];

/**
 * Determine whether an event type is security-relevant.
 *
 * @param eventType - Audit event type to classify.
 * @returns True when the event requires a security highlight.
 */
export function isSecurityEvent(eventType: AuditEventType): boolean {
  return SECURITY_EVENT_TYPES.includes(eventType);
}

/** Props accepted by the AuditDetail component. */
export interface AuditDetailProps {
  /** Entry to display, or null when nothing is selected. */
  entry: AuditEntry | null;
  /** Invoked when the modal requests to close. */
  onClose: () => void;
}

/** A single identifier row inside the detail grid. */
function IdentifierRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="break-all font-mono text-xs">{value ?? "—"}</dd>
    </div>
  );
}

/**
 * Modal showing the full detail of a single audit entry.
 *
 * @example
 * ```tsx
 * <AuditDetail entry={selected} onClose={() => setSelected(null)} />
 * ```
 */
export function AuditDetail({ entry, onClose }: AuditDetailProps) {
  const security = entry ? isSecurityEvent(entry.event_type) : false;

  const detailJson = React.useMemo(() => {
    if (!entry) return "";
    try {
      return JSON.stringify(entry.detail ?? {}, null, 2);
    } catch {
      return "Detail payload could not be serialized.";
    }
  }, [entry]);

  return (
    <Dialog
      open={entry !== null}
      onClose={onClose}
      title={entry ? entry.event_type : undefined}
      description={entry ? entry.summary : undefined}
      className={cn("max-w-2xl", security && "border-2 border-destructive")}
    >
      {entry ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={security ? "destructive" : "outline"}>
              {entry.event_type}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {formatTimestamp(entry.timestamp)}
            </span>
            {security ? (
              <span className="ml-auto flex items-center gap-1 text-xs font-semibold text-destructive">
                <ShieldAlert className="h-4 w-4" aria-hidden="true" />
                Security-relevant event
              </span>
            ) : null}
          </div>

          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <IdentifierRow label="Entry ID" value={entry.entry_id} />
            <IdentifierRow label="Tenant ID" value={entry.tenant_id} />
            <IdentifierRow label="Task ID" value={entry.task_id} />
            <IdentifierRow label="Subtask ID" value={entry.subtask_id} />
            <IdentifierRow
              label="Sub-subtask ID"
              value={entry.sub_subtask_id}
            />
            <IdentifierRow label="Agent ID" value={entry.agent_id} />
          </dl>

          <div className="space-y-1">
            <h3 className="text-xs uppercase tracking-wide text-muted-foreground">
              Detail payload
            </h3>
            <pre className="max-h-72 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
              <code>{detailJson}</code>
            </pre>
          </div>
        </div>
      ) : null}
    </Dialog>
  );
}
