"use client";

/**
 * Modal dialog built on a fixed overlay (no Radix dependency).
 *
 * Implements the WAI-ARIA modal dialog pattern (Requirement 9.2):
 * `role="dialog"` with `aria-modal="true"`, a title referenced through
 * `aria-labelledby`, Escape to close, backdrop click to close, a focus
 * trap while open, focus moved into the dialog on open, and focus
 * restored to the triggering element on close.
 *
 * @module components/ui/dialog
 */

import * as React from "react";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/** Props accepted by the Dialog component. */
export interface DialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Invoked when the dialog requests to close (Escape, backdrop, close button). */
  onClose: () => void;
  /** Accessible dialog title. */
  title?: string;
  /** Supporting description rendered under the title. */
  description?: string;
  /** Dialog body content. */
  children?: React.ReactNode;
  /** Optional footer content, typically action buttons. */
  footer?: React.ReactNode;
  /** Additional classes for the dialog panel. */
  className?: string;
}

/** Selector matching the elements a keyboard user can Tab to. */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/**
 * Collect the visible, focusable descendants of a container in DOM order.
 *
 * @param container - Element to search within.
 * @returns Focusable elements, excluding hidden ones.
 */
function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter(
    (element) =>
      element.offsetWidth > 0 ||
      element.offsetHeight > 0 ||
      element === document.activeElement,
  );
}

/**
 * Controlled modal dialog.
 *
 * @example
 * ```tsx
 * <Dialog open={open} onClose={() => setOpen(false)} title="Delete document">
 *   This action cannot be undone.
 * </Dialog>
 * ```
 */
function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
}: DialogProps) {
  const panelRef = React.useRef<HTMLDivElement | null>(null);
  const reactId = React.useId();
  const titleId = `dialog-title-${reactId}`;
  const descriptionId = `dialog-description-${reactId}`;

  // Escape to close, Tab cycling inside the panel, background scroll lock,
  // focus into the dialog on open, and focus restoration on close.
  React.useEffect(() => {
    if (!open) return;

    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const panel = panelRef.current;
    if (panel) {
      const focusables = focusableWithin(panel);
      // Prefer the first control inside the body/footer over the close
      // button so keyboard users land on a meaningful action.
      (focusables[focusables.length > 1 ? 1 : 0] ?? panel).focus();
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }

      if (event.key !== "Tab") return;

      const current = panelRef.current;
      if (!current) return;

      const focusables = focusableWithin(current);
      if (focusables.length === 0) {
        event.preventDefault();
        current.focus();
        return;
      }

      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;
      const active = document.activeElement;

      if (!current.contains(active)) {
        event.preventDefault();
        first.focus();
        return;
      }

      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : "Dialog"}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "relative z-10 w-full max-w-lg rounded-lg border border-border bg-card p-6 text-card-foreground shadow-lg focus-visible:outline-none",
          className,
        )}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close dialog"
          className="absolute right-2 top-2 inline-flex min-h-touch min-w-touch items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:right-4 md:top-4 md:min-h-0 md:min-w-0"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>

        {title ? (
          <h2
            id={titleId}
            className="pr-8 text-lg font-semibold leading-none tracking-tight"
          >
            {title}
          </h2>
        ) : null}

        {description ? (
          <p id={descriptionId} className="mt-2 text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}

        {children ? <div className="mt-4 text-sm">{children}</div> : null}

        {footer ? (
          <div className="mt-6 flex items-center justify-end gap-2">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export { Dialog };
