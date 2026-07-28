"use client";

/**
 * Paginated Knowledge Base document table.
 *
 * Filters the supplied documents by filename, slices the result with the
 * pure `paginate` utility, and exposes a per-row delete action guarded by
 * a confirmation dialog (backend enforces the `knowledge:admin` scope).
 *
 * @module components/knowledge/document-list
 */

import * as React from "react";
import { Trash2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { deleteDocument } from "@/lib/api/knowledge";
import { formatTimestamp } from "@/lib/utils/format";
import { paginate } from "@/lib/utils/pagination";
import type { KBDocument } from "@/types";

/** Documents rendered per page. */
const PAGE_SIZE = 20;

/** Column labels for the document table. */
const COLUMNS = ["Filename", "Type", "Uploaded", "Chunks", "Tokens", "Actions"];

/** Props for {@link DocumentList}. */
export interface DocumentListProps {
  /** Namespace the documents belong to. */
  namespace: string;
  /** Documents to display. */
  documents: KBDocument[];
  /** Invoked after a document is deleted successfully. */
  onDeleted?: (documentId: string) => void;
  /** Extra classes for the outer container. */
  className?: string;
}

/**
 * Document table with filename search, pagination, and delete action.
 *
 * @example
 * ```tsx
 * <DocumentList namespace="clinical" documents={docs} onDeleted={remove} />
 * ```
 */
export function DocumentList({
  namespace,
  documents,
  onDeleted,
  className,
}: DocumentListProps) {
  const [query, setQuery] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [pendingDelete, setPendingDelete] = React.useState<KBDocument | null>(
    null,
  );
  const [isDeleting, setIsDeleting] = React.useState(false);
  const [deleteError, setDeleteError] = React.useState<string | null>(null);

  // Reset paging when the namespace or search term changes.
  React.useEffect(() => {
    setOffset(0);
  }, [namespace, query]);

  const filtered = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return documents;
    return documents.filter((document) =>
      document.filename.toLowerCase().includes(needle),
    );
  }, [documents, query]);

  const page = React.useMemo(
    () => paginate(filtered, { offset, limit: PAGE_SIZE }),
    [filtered, offset],
  );

  const pageCount = Math.max(1, Math.ceil(page.total_count / PAGE_SIZE));
  const currentPage = Math.floor(page.offset / PAGE_SIZE) + 1;

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteDocument(pendingDelete.document_id);
      onDeleted?.(pendingDelete.document_id);
      setPendingDelete(null);
    } catch (err: unknown) {
      setDeleteError(
        err instanceof Error ? err.message : "Failed to delete document",
      );
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="sr-only" htmlFor="document-search">
          Search documents by filename
        </label>
        <Input
          id="document-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by filename…"
          className="max-w-xs"
        />
        <span className="text-xs text-muted-foreground">
          {page.total_count} document{page.total_count === 1 ? "" : "s"} in{" "}
          <span className="font-mono">{namespace}</span>
        </span>
      </div>

      <div className="rounded-lg border border-border">
        <Table>
          <caption className="sr-only">
            Documents in {namespace} with type, upload date, chunk count, and
            token totals
          </caption>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              {COLUMNS.map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.items.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <td
                  colSpan={COLUMNS.length}
                  className="px-3 py-10 text-center text-sm text-muted-foreground"
                >
                  {documents.length === 0
                    ? "This namespace has no documents yet."
                    : "No documents match the search."}
                </td>
              </TableRow>
            ) : (
              page.items.map((document) => (
                <TableRow key={document.document_id}>
                  <TableCell className="max-w-[20rem]">
                    <span className="block truncate font-medium">
                      {document.filename}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className="whitespace-nowrap">
                      {document.file_type}
                    </Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                    {formatTimestamp(document.uploaded_at)}
                  </TableCell>
                  <TableCell className="tabular-nums text-xs">
                    {document.chunk_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="tabular-nums text-xs">
                    {document.total_tokens.toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setDeleteError(null);
                        setPendingDelete(document);
                      }}
                      aria-label={`Delete ${document.filename}`}
                      aria-haspopup="dialog"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                      Delete
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>

        <nav
          aria-label="Document pagination"
          className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2"
        >
          <p
            className="text-xs text-muted-foreground"
            aria-live="polite"
            aria-atomic="true"
          >
            Page {currentPage} of {pageCount}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={page.offset === 0}
              aria-label="Go to previous page of documents"
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={page.offset + PAGE_SIZE >= page.total_count}
              aria-label="Go to next page of documents"
            >
              Next
            </Button>
          </div>
        </nav>
      </div>

      <Dialog
        open={pendingDelete !== null}
        onClose={() => {
          if (!isDeleting) setPendingDelete(null);
        }}
        title="Delete document"
        description="This removes the document and all of its chunks from the vector store. This action cannot be undone."
        footer={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPendingDelete(null)}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => void confirmDelete()}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting…" : "Delete"}
            </Button>
          </>
        }
      >
        <p>
          Delete <span className="font-medium">{pendingDelete?.filename}</span>{" "}
          from <span className="font-mono">{namespace}</span>?
        </p>
        {deleteError ? (
          <p role="alert" className="mt-3 text-destructive">
            {deleteError}
          </p>
        ) : null}
      </Dialog>
    </div>
  );
}
