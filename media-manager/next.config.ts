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
  // No image optimizer route (it is not used, and this removes the
  // image-optimization attack surface).
  images: { unoptimized: true },
  // Load these packages from node_modules at run time and do not bundle
  // them. server.ts loads them too, so the process uses one copy.
  serverExternalPackages: ["postgres", "file-type"],
  typescript: { tsconfigPath: "tsconfig.json" },
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
