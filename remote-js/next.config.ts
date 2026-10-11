import type { NextConfig } from "next";
import { SECURITY_HEADERS } from "./src/server/security.ts";

const nextConfig: NextConfig = {
  output: "standalone",
  // The repository root has its own lockfile. Use this folder as the root,
  // so that the standalone output has server files at its top level.
  outputFileTracingRoot: import.meta.dirname,
  turbopack: { root: import.meta.dirname },
  // The old router is strict about trailing slashes and never redirects.
  skipTrailingSlashRedirect: true,
  poweredByHeader: false,
  // The old service did not compress responses. With compression, Next.js
  // adds "Vary: Accept-Encoding" and removes the Content-Length of JSON
  // bodies of 1 KiB or more. Traefik can compress if that becomes necessary.
  compress: false,
  // No image optimizer route (it is not used, and this removes the
  // image-optimization attack surface).
  images: { unoptimized: true },
  // Load these packages from node_modules at run time and do not bundle
  // them. server.ts loads them too, so the process uses one copy.
  serverExternalPackages: ["postgres", "file-type"],
  typescript: { tsconfigPath: "tsconfig.json" },
  // unauthorized() and app/unauthorized.tsx: a page with a bad media token
  // gets an HTML error page with status 401 (the API keeps the JSON 401).
  experimental: { authInterrupts: true },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: Object.entries(SECURITY_HEADERS).map(([key, value]) => ({ key, value })),
      },
    ];
  },
};

export default nextConfig;
