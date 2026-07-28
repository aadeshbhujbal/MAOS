"use client";

/**
 * Dark/light theme toggle button.
 *
 * Reads and mutates the Zustand theme store, which persists the
 * preference to localStorage and toggles the `dark` class on
 * `document.documentElement`.
 *
 * @module components/layout/theme-toggle
 */

import { useEffect } from "react";
import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useThemeStore } from "@/lib/stores/theme-store";

/**
 * Icon button that switches between dark and light mode.
 *
 * Calls `initTheme()` once on mount to restore the stored preference
 * (or the system preference when none is stored).
 */
export function ThemeToggle() {
  const theme = useThemeStore((state) => state.theme);
  const toggleTheme = useThemeStore((state) => state.toggleTheme);
  const initTheme = useThemeStore((state) => state.initTheme);

  useEffect(() => {
    initTheme();
  }, [initTheme]);

  const isDark = theme === "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      title={isDark ? "Switch to light theme" : "Switch to dark theme"}
    >
      {isDark ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </Button>
  );
}
