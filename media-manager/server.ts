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
 * configureServerTimeouts() (src/server/http.ts) gives the same behavior:
 * no keep-alive idle timeout, no request timeout, no socket timeout.
 *
 * Body limit: the old Bun server refused a request body above 128 MiB
 * (`maxRequestBodySize`) before a route saw it. enforceRequestBodyLimit()
 * (src/server/http.ts) does the same for each request, first.
 */

import { readFileSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import next from "next";
import { releaseResources, runStartup } from "./src/server/startup.ts";
import { SECURITY_HEADERS } from "./src/server/security.ts";
import { CLIENT_IP_HEADER, resolveClientIp } from "./src/server/clientIp.ts";
import { classifyAdminRequest } from "./src/server/adminPaths.ts";
import { checkLoginRateLimit } from "./src/server/auth.ts";
import {
  ADMIN_TOKEN_RATE_LIMIT_LABEL, ADMIN_TOO_MANY_ATTEMPTS, configureServerTimeouts, enforceRequestBodyLimit,
} from "./src/server/http.ts";

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
 * HEAD: `Content-Length: 0`, as the old service sent (not for a stream
 * response, which keeps its length).
 *
 * Vary: Next.js adds `Vary: rsc, next-router-state-tree, ...` to each app-route
 * response. The header is necessary only for pages (an HTML document and its
 * RSC payload use the same URL). The old API responses had no Vary header,
 * so remove it when the response is not HTML and not an RSC payload. A Vary
 * header that a route handler sets itself does not start with "rsc" and stays.
 */
const ROUTER_VARY = new Set(["rsc", "next-router-state-tree", "next-router-prefetch", "next-router-segment-prefetch", "next-url"]);

const NEXT_PAGE_CACHE_CONTROL = "private, no-cache, no-store, max-age=0, must-revalidate";

function adjustHeaders(req: http.IncomingMessage, res: http.ServerResponse): void {
  const writeHead = res.writeHead;
  res.writeHead = function (this: http.ServerResponse, ...args: unknown[]) {
    // The old Bun/Hono server sent "Content-Length: 0" on each HEAD
    // response. Next.js sends the length of the GET body. Keep the old value.
    // Exception: a stream response (it has Accept-Ranges). The old stream
    // route set Content-Length itself, so its HEAD response kept the GET
    // length (verified against the old service, #58).
    if (req.method === "HEAD" && !this.hasHeader("accept-ranges")) this.setHeader("content-length", "0");
    const raw = this.getHeader("vary");
    const type = String(this.getHeader("content-type") ?? "");
    // Next.js adds this Cache-Control to each dynamic HTML page. The old
    // service sent the project and admin HTML pages with no Cache-Control
    // (verified with the old image), so remove it. Route handlers get no
    // Cache-Control from Next.js. RSC payloads and /_next/static assets have
    // no old equivalent and keep their headers.
    if (/^text\/html/.test(type) && this.getHeader("cache-control") === NEXT_PAGE_CACHE_CONTROL) {
      this.removeHeader("cache-control");
    }
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
 * method handling. The admin paths have the same rule in
 * src/server/adminPaths.ts (#63).
 */
function isPageMethodNotAllowed(method: string | undefined, url: string | undefined): boolean {
  if (method === "GET" || method === "HEAD") return false;
  const pathname = (url ?? "").split("?", 1)[0] ?? "";
  const parts = pathname.split("/");
  // ["", "projects", token, project, ...rest]
  return parts[1] === "projects" && parts.length >= 4 && parts[4] !== "api";
}

function sendNotFound(req: http.IncomingMessage, res: http.ServerResponse): void {
  sendDetail(req, res, 404, "Not Found");
}

function sendDetail(
  req: http.IncomingMessage, res: http.ServerResponse, status: number, message: string,
  headers: Record<string, string> = {},
): void {
  const body = req.method === "HEAD" ? "" : JSON.stringify({ detail: message });
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) res.setHeader(name, value);
  res.writeHead(status, { ...headers, "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  res.end(body);
}

/**
 * Admin paths (#63, see src/server/adminPaths.ts). Returns true when this
 * function sent the response.
 *
 * A page path first gets the admin-token rate limit: a blocked client gets
 * the JSON 429 with Retry-After, as from the old service. A page cannot set
 * that status, so the check is here. The page itself checks the token, and
 * records a failure or clears the counter.
 */
function handleAdminPath(req: http.IncomingMessage, res: http.ServerResponse, clientIp: string): boolean {
  const action = classifyAdminRequest(req.method, req.url);
  if (action.kind === "pass") return false;
  if (action.kind === "notFound") {
    sendNotFound(req, res);
    return true;
  }
  const limited = checkLoginRateLimit(clientIp, ADMIN_TOKEN_RATE_LIMIT_LABEL);
  if (limited) {
    sendDetail(req, res, 429, ADMIN_TOO_MANY_ATTEMPTS, { "retry-after": String(limited.retryAfterSeconds) });
    return true;
  }
  if (action.url) req.url = action.url;
  return false;
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
    if (enforceRequestBodyLimit(req)) return;
    if (isImageOptimizerPath(req.url) || isPageMethodNotAllowed(req.method, req.url)) {
      return sendNotFound(req, res);
    }
    // Route handlers have no socket address. Give them the client IP in an
    // internal header, and replace any copy that the client sent (#63).
    const clientIp = resolveClientIp(req.socket.remoteAddress, req.headers["x-forwarded-for"]);
    req.headers[CLIENT_IP_HEADER] = clientIp;
    if (handleAdminPath(req, res, clientIp)) return;
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
  configureServerTimeouts(server);

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
