/**
 * Cross-route HTTP helpers - peer-IP extraction, JSON normalization, and the
 * shared verifyToken / verifyAdminToken guards that mirror the FastAPI ones
 * in remote/app.py.
 */

import type { Context } from "hono";
import {
  checkLoginRateLimit,
  clearLoginRateLimit,
  recordFailedLogin,
  verifyStoredToken,
} from "./auth.ts";
import { HttpError } from "./schemas.ts";

/** Bun's `Bun.serve` exposes the peer IP via `c.env.requestIP(req)`. */
export function getPeerIp(c: Context): string {
  const env = c.env as
    | { requestIP?: (req: Request) => { address: string } | null }
    | undefined;
  if (env?.requestIP) {
    try {
      const info = env.requestIP(c.req.raw);
      if (info?.address) return info.address;
    } catch {
      // fall through
    }
  }
  return "unknown";
}

/** Verify the token from the URL against the media-token hash. */
export async function verifyMediaToken(token: string): Promise<void> {
  const ok = await verifyStoredToken("media", token);
  if (!ok) {
    throw new HttpError(401, "Invalid token");
  }
}

/**
 * Verify an admin URL token and rate-limit invalid attempts by peer IP.
 * Mirrors `verify_admin_token` in remote/app.py.
 */
export async function verifyAdminToken(
  c: Context,
  adminToken: string,
): Promise<void> {
  const peerIp = getPeerIp(c);
  const limited = checkLoginRateLimit(peerIp, "admin-token");
  if (limited) {
    throw new HttpError(429, "Too many admin login attempts. Try again later.", {
      "Retry-After": String(limited.retryAfterSeconds),
    });
  }
  const ok = await verifyStoredToken("admin", adminToken);
  if (ok) {
    clearLoginRateLimit(peerIp, "admin-token");
    return;
  }
  recordFailedLogin(peerIp, "admin-token");
  throw new HttpError(401, "Invalid admin token");
}
