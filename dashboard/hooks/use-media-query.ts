"use client";

/**
 * Media query hook used for breakpoint-dependent defaults.
 *
 * @module hooks/use-media-query
 */

import { useEffect, useState } from "react";

/** The `md` breakpoint from `tailwind.config.ts` (tablet and wider). */
export const MD_BREAKPOINT_QUERY = "(min-width: 768px)";

/**
 * Track whether a CSS media query currently matches.
 *
 * Always returns `false` on the server and on the first client render so
 * that server and client markup agree; the real value is applied after
 * mount. Callers should therefore treat `false` as the mobile-first
 * default (e.g. collapsed tree branches).
 *
 * @param query - A CSS media query string.
 * @returns True when the query matches the current viewport.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;

    const mediaQueryList = window.matchMedia(query);
    const update = () => setMatches(mediaQueryList.matches);

    update();
    mediaQueryList.addEventListener("change", update);
    return () => mediaQueryList.removeEventListener("change", update);
  }, [query]);

  return matches;
}

/**
 * Convenience wrapper for the `md` (tablet and wider) breakpoint.
 *
 * @returns True when the viewport is at least 768px wide.
 */
export function useIsDesktop(): boolean {
  return useMediaQuery(MD_BREAKPOINT_QUERY);
}
