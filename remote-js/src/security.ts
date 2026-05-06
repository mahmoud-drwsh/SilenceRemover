/**
 * Security-header middleware. Mirrors the `SECURITY_HEADERS` block in
 * remote/app.py.
 */

import { createMiddleware } from "hono/factory";

const SECURITY_HEADERS: Record<string, string> = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "same-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Content-Security-Policy": [
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "connect-src 'self'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self' 'unsafe-inline'",
  ].join("; "),
};

/**
 * Hono middleware that sets each security header only when the response
 * doesn't already declare it. Matches FastAPI `headers.setdefault` behavior.
 */
export const securityHeaders = createMiddleware(async (c, next) => {
  await next();
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    if (!c.res.headers.has(name)) {
      c.res.headers.set(name, value);
    }
  }
});
