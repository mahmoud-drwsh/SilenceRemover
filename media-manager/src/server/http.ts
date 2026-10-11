/**
 * Shared HTTP helpers for the Next.js route handlers.
 *
 * - All errors are `{detail}` JSON, as in remote-js/src/index.ts.
 * - `route()` wraps a handler: an HttpError becomes its status, its headers,
 *   and `{detail: message}`. Any other error is logged with "[ERROR]" and
 *   becomes 500 `{detail: "Internal server error"}`.
 * - `notFoundRoute` answers every method with 404 `{detail: "Not Found"}`.
 *   Export it from each route file for the methods that the file does not
 *   serve, so that Next.js does not answer them with 405 or with its
 *   automatic OPTIONS response.
 */

import {
  checkLoginRateLimit,
  clearLoginRateLimit,
  recordFailedLogin,
  verifyStoredToken,
} from "./auth.ts";
import { HttpError } from "./schemas.ts";

export { HttpError };

/**
 * JSON response with the same body and headers as Hono's `c.json()` on Bun:
 * `Content-Type: application/json` and a `Content-Length` (Next.js sends a
 * body without Content-Length as chunked).
 */
export function json(body: unknown, status = 200, headers?: HeadersInit): Response {
  const text = JSON.stringify(body);
  const merged = new Headers(headers);
  merged.set("Content-Type", "application/json");
  merged.set("Content-Length", String(Buffer.byteLength(text)));
  return new Response(text, { status, headers: merged });
}

/** The `{detail}` error response. */
export function detail(status: number, message: string, headers?: HeadersInit): Response {
  return json({ detail: message }, status, headers);
}

/** Convert a thrown value to the `{detail}` response. */
export function errorResponse(err: unknown): Response {
  if (err instanceof HttpError) {
    return detail(err.status, err.message, err.headers);
  }
  console.error("[ERROR]", err);
  return detail(500, "Internal server error");
}

/** Response for a path or a method that has no route. */
export function notFound(): Response {
  return detail(404, "Not Found");
}

/** Route handler that answers 404 `{detail: "Not Found"}` for any request. */
export function notFoundRoute(): Response {
  return notFound();
}

/**
 * True when the request path ends with "/" (and is not "/"). The old Hono
 * router is strict: "/healthz/" does not match "/healthz". Next.js removes
 * the trailing slash before it matches a route, so each route handler must
 * call this and answer 404 when it is true. (With `skipTrailingSlashRedirect`
 * Next.js does not send a 308 redirect.)
 */
export function hasTrailingSlash(request: Request): boolean {
  const { pathname } = new URL(request.url);
  return pathname.length > 1 && pathname.endsWith("/");
}

type Handler<C> = (request: Request, context: C) => Response | Promise<Response>;

/**
 * Wrap a route handler with the shared error mapping and the strict
 * trailing-slash rule.
 */
export function route<C>(handler: Handler<C>): Handler<C> {
  return async (request, context) => {
    if (hasTrailingSlash(request)) return notFound();
    try {
      return await handler(request, context);
    } catch (err) {
      return errorResponse(err);
    }
  };
}

/** Verify the token from the URL against the media-token hash. */
export async function verifyMediaToken(token: string): Promise<void> {
  const ok = await verifyStoredToken("media", token);
  if (!ok) {
    throw new HttpError(401, "Invalid token");
  }
}

/** Rate-limit label and 429 text of the admin-token check. */
export const ADMIN_TOKEN_RATE_LIMIT_LABEL = "admin-token";
export const ADMIN_TOO_MANY_ATTEMPTS = "Too many admin login attempts. Try again later.";

/**
 * Check an admin URL token for a client IP (see src/server/clientIp.ts).
 * The rate limit comes first (no database read for a blocked client). A bad
 * token records a failure; a good token clears the counter.
 */
export async function checkAdminToken(
  clientIp: string,
  adminToken: string,
): Promise<"ok" | "invalid" | { retryAfterSeconds: number }> {
  const limited = checkLoginRateLimit(clientIp, ADMIN_TOKEN_RATE_LIMIT_LABEL);
  if (limited) return limited;
  if (await verifyStoredToken("admin", adminToken)) {
    clearLoginRateLimit(clientIp, ADMIN_TOKEN_RATE_LIMIT_LABEL);
    return "ok";
  }
  recordFailedLogin(clientIp, ADMIN_TOKEN_RATE_LIMIT_LABEL);
  return "invalid";
}

/**
 * Verify an admin URL token and rate-limit invalid attempts by client IP:
 * 429 with Retry-After, or 401 `Invalid admin token`.
 */
export async function verifyAdminToken(clientIp: string, adminToken: string): Promise<void> {
  const result = await checkAdminToken(clientIp, adminToken);
  if (result === "ok") return;
  if (result === "invalid") throw new HttpError(401, "Invalid admin token");
  throw new HttpError(429, ADMIN_TOO_MANY_ATTEMPTS, {
    "Retry-After": String(result.retryAfterSeconds),
  });
}
