export const SECURITY_HEADERS: Record<string, string> = {
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "same-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  "Content-Security-Policy":
    "default-src 'self'; " +
    "base-uri 'self'; " +
    "frame-ancestors 'none'; " +
    "form-action 'self'; " +
    "connect-src 'self'; " +
    "img-src 'self' data: blob:; " +
    "media-src 'self' blob:; " +
    "style-src 'self' 'unsafe-inline'; " +
    "script-src 'self' 'unsafe-inline'",
};
