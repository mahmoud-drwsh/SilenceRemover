/**
 * Media Manager entry script. Node.js runs this file directly (Node strips the
 * TypeScript types), so this file and src/server/** use only erasable syntax
 * and relative imports with the ".ts" extension.
 *
 * Order:
 *   1. runStartup(): configuration, schema, re-queue, S3 check, upload-session
 *      cleanup. If a step fails, the process logs "[startup-error]" and stops
 *      with exit code 1. The HTTP port is not open during these steps, so
 *      nothing (also not /healthz) can answer before the startup is done.
 *   2. Prepare the Next.js standalone app.
 *   3. Open the HTTP server on 0.0.0.0:PORT.
 *
 * Timeouts: the old Bun server used `idleTimeout: 0` (no idle timeout).
 * Node's defaults would stop a request body that takes longer than 300 s
 * (`requestTimeout`). We set `requestTimeout = 0`, so that long uploads and
 * long streams do not get cut. `server.timeout` (socket idle) is 0 by default.
 * `headersTimeout` stays at 60 s; it applies only to receiving the request
 * headers, not to the body or to the response.
 */

import { readFileSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import next from "next";
import { releaseResources, runStartup } from "./src/server/startup.ts";
import { SECURITY_HEADERS } from "./src/server/security.ts";

const dir = import.meta.dirname;

function loadStandaloneConfig(): Record<string, unknown> | undefined {
  try {
    const file = path.join(dir, ".next", "required-server-files.json");
    const parsed = JSON.parse(readFileSync(file, "utf8")) as { config?: Record<string, unknown> };
    return parsed.config;
  } catch {
    return undefined;
  }
}

/**
 * Header changes just before the status line is written:
 *
 * HEAD: `Content-Length: 0`, as the old service sent.
 *
 * Vary: Next.js adds `Vary: rsc, next-router-state-tree, ...` to each app-route
 * response. The header is necessary only for pages (an HTML document and its
 * RSC payload use the same URL). The old API responses had no Vary header,
 * so remove it when the response is not HTML and not an RSC payload. A Vary
 * header that a route handler sets itself does not start with "rsc" and stays.
 */
const ROUTER_VARY = new Set(["rsc", "next-router-state-tree", "next-router-prefetch", "next-router-segment-prefetch", "next-url"]);

function adjustHeaders(req: http.IncomingMessage, res: http.ServerResponse): void {
  const writeHead = res.writeHead;
  res.writeHead = function (this: http.ServerResponse, ...args: unknown[]) {
    // The old Bun/Hono server sent "Content-Length: 0" on each HEAD
    // response. Next.js sends the length of the GET body. Keep the old value.
    if (req.method === "HEAD") this.setHeader("content-length", "0");
    const raw = this.getHeader("vary");
    const type = String(this.getHeader("content-type") ?? "");
    if (raw !== undefined && !/^text\/(html|x-component)/.test(type)) {
      const values = (Array.isArray(raw) ? raw.join(",") : String(raw))
        .split(",").map((v) => v.trim()).filter(Boolean);
      const kept = values.filter((v) => !ROUTER_VARY.has(v.toLowerCase()));
      if (kept.length === 0) this.removeHeader("vary");
      else if (kept.length !== values.length) this.setHeader("vary", kept.join(", "));
    }
    return (writeHead as (...a: unknown[]) => http.ServerResponse).apply(this, args);
  } as typeof res.writeHead;
}

/**
 * The app does not use the Next.js image optimizer (`images.unoptimized`).
 * Next.js still has the /_next/image path and answers it with an HTML 404.
 * The old service answered every unknown path with the JSON 404, so this
 * path gets it before Next.js sees the request.
 */
function isImageOptimizerPath(url: string | undefined): boolean {
  const pathname = (url ?? "").split("?", 1)[0] ?? "";
  return pathname === "/_next/image" || pathname.startsWith("/_next/image/");
}

/**
 * Next.js renders a page for any method (a POST can also start a server
 * action). The old service served the project pages for GET only, and the
 * app uses no server actions. So a request with another method to a path
 * under /projects/<token>/<project>/ that is not under ".../api" gets the
 * JSON 404 here, before Next.js sees it. The API routes have their own
 * method handling. (#63 adds the same rule for the admin pages, without the
 * removed "/admin/<token>/files" routes, which have their own handler.)
 */
function isPageMethodNotAllowed(method: string | undefined, url: string | undefined): boolean {
  if (method === "GET" || method === "HEAD") return false;
  const pathname = (url ?? "").split("?", 1)[0] ?? "";
  const parts = pathname.split("/");
  // ["", "projects", token, project, ...rest]
  return parts[1] === "projects" && parts.length >= 4 && parts[4] !== "api";
}

function sendNotFound(req: http.IncomingMessage, res: http.ServerResponse): void {
  const body = req.method === "HEAD" ? "" : JSON.stringify({ detail: "Not Found" });
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) res.setHeader(name, value);
  res.writeHead(404, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  res.end(body);
}

async function main(): Promise<void> {
  const config = await runStartup();

  const nextConfig = loadStandaloneConfig();
  if (nextConfig) {
    // The same step as the generated standalone server.js.
    process.env.__NEXT_PRIVATE_STANDALONE_CONFIG = JSON.stringify(nextConfig);
  }
  const app = next({
    dev: false,
    dir,
    hostname: "0.0.0.0",
    port: config.port,
    ...(nextConfig ? { conf: nextConfig } : {}),
  });
  await app.prepare();
  const handle = app.getRequestHandler();

  const server = http.createServer((req, res) => {
    if (isImageOptimizerPath(req.url) || isPageMethodNotAllowed(req.method, req.url)) {
      return sendNotFound(req, res);
    }
    adjustHeaders(req, res);
    handle(req, res).catch((error: unknown) => {
      console.error("[server error]", error);
      if (!res.headersSent) {
        res.statusCode = 500;
        res.end("Internal server error");
      } else {
        res.destroy();
      }
    });
  });
  server.requestTimeout = 0;
  server.timeout = 0;

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.port, "0.0.0.0", () => resolve());
  });
  console.log("[startup] checks passed; listening on :" + config.port);

  let stopping = false;
  const shutdown = async (signal: NodeJS.Signals) => {
    if (stopping) return;
    stopping = true;
    console.log(`[shutdown] ${signal} received; closing server`);
    // Stop accepting new connections. Requests in progress can continue
    // until the process exits, as with Bun's server.stop().
    server.close();
    server.closeIdleConnections();
    await releaseResources();
    process.exit(0);
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  console.error("[startup-error]", err);
  process.exit(1);
});
