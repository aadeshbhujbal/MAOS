import type { Metadata, Viewport } from "next";

import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "MAOS Dashboard",
  description:
    "Multi-Agent Orchestration System — Real-time monitoring and management dashboard",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

/**
 * Root layout composing the sidebar navigation, header, and main content.
 *
 * `suppressHydrationWarning` is set on `<html>` because the theme store
 * toggles the `dark` class on the document element on the client, which
 * would otherwise mismatch the server-rendered markup.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        {/*
          Skip navigation link (Requirement 9.2). First focusable element in
          the document, visually hidden until it receives focus, and targets
          the `<main>` region so keyboard users can bypass the sidebar.
        */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:border focus:border-input focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-ring"
        >
          Skip to main content
        </a>

        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <Header />
            <main
              id="main-content"
              tabIndex={-1}
              className="w-full min-w-0 flex-1 p-3 outline-none xs:p-4 md:p-6 3xl:mx-auto 3xl:max-w-[1800px] 3xl:p-8"
            >
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
