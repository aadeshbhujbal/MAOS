/**
 * Next.js configuration.
 *
 * Written as `.mjs` because Next 14 does not load a TypeScript config file
 * (`next.config.ts` support landed in Next 15). The JSDoc type annotation
 * keeps editor type checking without needing a TypeScript config.
 *
 * @type {import("next").NextConfig}
 */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",

  /**
   * Rewrites proxy `/v1/*` to the internal mock API route handlers at
   * `/api/v1/*` when NEXT_PUBLIC_MAOS_API_URL points at localhost:3000.
   * Remove this block when connecting to the real MAOS FastAPI backend.
   */
  async rewrites() {
    return [
      {
        source: "/v1/:path*",
        destination: "/api/v1/:path*",
      },
    ];
  },
};

export default nextConfig;
