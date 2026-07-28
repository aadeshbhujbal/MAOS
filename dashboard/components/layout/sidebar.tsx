"use client";

/**
 * Sidebar navigation for the MAOS dashboard.
 *
 * Renders links to the six dashboard sections, highlights the active
 * route, collapses below the `md` breakpoint behind the header's
 * hamburger toggle, and supports Alt+1..Alt+6 keyboard shortcuts for
 * fast section switching.
 *
 * @module components/layout/sidebar
 */

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BookOpen,
  DollarSign,
  ListChecks,
  ScrollText,
  Users,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/lib/stores/sidebar-store";

/** A single sidebar navigation entry. */
interface NavItem {
  /** Visible label. */
  label: string;
  /** Route path. */
  href: string;
  /** Icon rendered beside the label. */
  icon: LucideIcon;
  /** Alt+N shortcut digit for this section. */
  shortcut: string;
}

/**
 * Dashboard navigation items in shortcut order (Alt+1 through Alt+6).
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { label: "Tasks", href: "/tasks", icon: ListChecks, shortcut: "1" },
  { label: "Agents", href: "/agents", icon: Users, shortcut: "2" },
  { label: "Costs", href: "/costs", icon: DollarSign, shortcut: "3" },
  { label: "Health", href: "/health", icon: Activity, shortcut: "4" },
  { label: "Knowledge", href: "/knowledge", icon: BookOpen, shortcut: "5" },
  { label: "Audit", href: "/audit", icon: ScrollText, shortcut: "6" },
] as const;

/**
 * Determine whether a nav item matches the current pathname.
 *
 * A section is active for its own path and any nested route beneath it
 * (e.g. `/tasks/abc` keeps the Tasks link active).
 *
 * @param pathname - Current pathname from the router.
 * @param href - Nav item route.
 * @returns True when the nav item should render as active.
 */
export function isActiveRoute(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Responsive sidebar navigation.
 *
 * Below `md` (768px) the sidebar renders as an overlay drawer with a
 * backdrop, driven by the hamburger button in the header; at `md` and
 * wider it is a permanently visible static column.
 */
export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const isOpen = useSidebarStore((state) => state.isOpen);
  const close = useSidebarStore((state) => state.close);

  // Alt+1..Alt+6 jump straight to a section.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.ctrlKey || event.metaKey) return;
      const item = NAV_ITEMS.find((nav) => nav.shortcut === event.key);
      if (!item) return;
      event.preventDefault();
      close();
      router.push(item.href);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router, close]);

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };

    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [isOpen, close]);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    close();
  }, [pathname, close]);

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen ? (
        <div
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={close}
          aria-hidden="true"
        />
      ) : null}

      <aside
        id="dashboard-sidebar"
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 shrink-0 flex-col border-r border-border bg-card transition-transform duration-200 md:static md:visible md:translate-x-0",
          isOpen ? "translate-x-0" : "invisible -translate-x-full",
        )}
      >
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <span className="text-sm font-semibold tracking-tight">MAOS</span>
          <span className="text-xs text-muted-foreground">Orchestration</span>
        </div>

        <nav aria-label="Dashboard sections" className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map(({ label, href, icon: Icon, shortcut }) => {
            const active = isActiveRoute(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                title={`${label} (Alt+${shortcut})`}
                onClick={close}
                className={cn(
                  "flex min-h-touch items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="flex-1">{label}</span>
                <kbd className="hidden rounded border border-border px-1 text-[10px] text-muted-foreground md:inline-block">
                  Alt+{shortcut}
                </kbd>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border p-3 text-xs text-muted-foreground">
          Use Alt+1 – Alt+6 to switch sections
        </div>
      </aside>
    </>
  );
}
