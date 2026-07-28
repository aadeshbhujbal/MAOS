"use client";

/**
 * Dashboard header with live WebSocket connection status and theme toggle.
 *
 * @module components/layout/header
 */

import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useWSStore } from "@/lib/stores/ws-store";
import { useSidebarStore } from "@/lib/stores/sidebar-store";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { NAV_ITEMS, isActiveRoute } from "@/components/layout/sidebar";
import type { ConnectionStatus } from "@/types";

/**
 * Visual presentation for each connection status.
 *
 * Dot colors are picked to clear 3:1 against the page background in both
 * themes (SC 1.4.11), and each dot is always paired with the visible text
 * label below so status is never conveyed by color alone (SC 1.4.1).
 */
const STATUS_PRESENTATION: Record<
  ConnectionStatus,
  { label: string; dotClass: string }
> = {
  connected: { label: "Connected", dotClass: "bg-green-600 dark:bg-green-500" },
  reconnecting: {
    label: "Reconnecting",
    dotClass: "bg-yellow-700 dark:bg-yellow-500 animate-pulse",
  },
  disconnected: {
    label: "Disconnected",
    dotClass: "bg-red-600 dark:bg-red-500",
  },
};

/**
 * Live connection status indicator.
 *
 * Green = connected, pulsing yellow = reconnecting, red = disconnected.
 */
export function ConnectionIndicator() {
  const status = useWSStore((state) => state.status);
  const { label, dotClass } = STATUS_PRESENTATION[status];

  return (
    <div
      className="flex items-center gap-2 rounded-full border border-input px-3 py-1"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <span
        className={cn("h-2 w-2 rounded-full", dotClass)}
        aria-hidden="true"
      />
      <span className="text-xs font-medium text-muted-foreground">
        <span className="sr-only">Realtime connection: </span>
        {label}
      </span>
    </div>
  );
}

/**
 * Hamburger button that opens and closes the mobile sidebar drawer.
 *
 * Hidden at the `md` breakpoint and wider, where the sidebar is always
 * visible. Sized to a 44x44px touch target.
 */
export function SidebarToggle() {
  const isOpen = useSidebarStore((state) => state.isOpen);
  const toggle = useSidebarStore((state) => state.toggle);

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isOpen ? "Close navigation" : "Open navigation"}
      aria-expanded={isOpen}
      aria-controls="dashboard-sidebar"
      className="-ml-1 inline-flex min-h-touch min-w-touch shrink-0 items-center justify-center rounded-md border border-input bg-card text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
    >
      {isOpen ? (
        <X className="h-5 w-5" aria-hidden="true" />
      ) : (
        <Menu className="h-5 w-5" aria-hidden="true" />
      )}
    </button>
  );
}

/**
 * Derive the current section title from the pathname.
 *
 * @param pathname - Current pathname from the router.
 * @returns The matching section label, or null when no section matches.
 */
function getSectionLabel(pathname: string | null): string | null {
  const match = NAV_ITEMS.find((item) => isActiveRoute(pathname, item.href));
  return match?.label ?? null;
}

/**
 * Top header bar: dashboard title, current section, connection status,
 * and theme toggle.
 */
export function Header() {
  const pathname = usePathname();
  const section = getSectionLabel(pathname);

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-background/95 px-3 backdrop-blur md:px-6">
      <SidebarToggle />

      <div className="flex min-w-0 flex-col">
        <h1 className="truncate text-sm font-semibold leading-tight">
          MAOS Dashboard
        </h1>
        {section ? (
          <span className="truncate text-xs text-muted-foreground">
            {section}
          </span>
        ) : null}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <ConnectionIndicator />
        <ThemeToggle />
      </div>
    </header>
  );
}
