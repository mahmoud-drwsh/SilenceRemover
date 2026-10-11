/**
 * Global security headers. The values are the same as the old Bun service file security.ts.
 *
 * next.config.ts applies them to all paths through `headers()`. Next.js sets
 * config headers before the route handler runs, and a header that the handler
 * sets replaces the config value. This gives the same "set only when the
 * response does not have it" result as the old middleware.
 *
 * The CSP did not change for Next.js: production Next.js pages need only
 * 'self' scripts plus inline scripts, and the old CSP already allows them.
 */

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
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
