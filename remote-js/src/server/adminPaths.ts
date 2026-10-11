/**
 * Request routing rules for /admin/<token>/* that Next.js cannot express
 * (#63). server.ts calls `classifyAdminRequest()` before Next.js sees the
 * request.
 *
 * The old Hono service had the admin API routes plus a `GET /admin/:token/*`
 * catch-all that served the admin page after the token check. So:
 * - A GET (or HEAD) to any admin path that is not a GET API route (for
 *   example /admin/A, /admin/A/api/unknown, the GET of a POST-only API
 *   path, or an API path with a trailing slash) got the admin page.
 * - Any other method on such a path got the JSON 404, with no token check.
 * - /admin/A/files and /admin/A/files/* (all methods) had their own handler.
 *
 * In Next.js the admin page is app/admin/[token]/[[...rest]]/page.tsx. Next
 * sends a GET of a POST-only API path (and an API path with a trailing slash,
 * because Next removes the slash before it matches) to the route handler,
 * not to the page. For these paths server.ts changes the request URL to
 * /admin/<token>, so that Next renders the page. The browser keeps the URL
 * that it asked for. A non-GET request to a page path would make Next render
 * the page (or try a server action), so server.ts answers the JSON 404.
 */

/** The result for one request. */
export type AdminRequestAction =
  /** Not an admin path, or an admin route that answers itself. */
  | { kind: "pass" }
  /** JSON 404 `Not Found`, before Next.js. */
  | { kind: "notFound" }
  /** Render the admin page. `url` is set when server.ts must change the request URL. */
  | { kind: "page"; token: string; url?: string };

type ApiRoute = { pattern: RegExp; method: "GET" | "POST" };

// The admin API route files under app/admin/[token]/api/ (no trailing slash).
const API_ROUTES: ApiRoute[] = [
  { pattern: /^projects$/, method: "GET" },
  { pattern: /^projects\/s3-storage$/, method: "GET" },
  { pattern: /^projects\/[^/]+\/source-processing\/status$/, method: "GET" },
  { pattern: /^refresh-admin-token$/, method: "POST" },
  { pattern: /^refresh-token$/, method: "POST" },
  { pattern: /^media-token$/, method: "POST" },
  { pattern: /^projects\/[^/]+\/source-processing\/[^/]+\/retry$/, method: "POST" },
];

/**
 * Decide how server.ts handles a request.
 *
 * @param method the request method.
 * @param url the raw request URL (path and query, not decoded).
 */
export function classifyAdminRequest(method: string | undefined, url: string | undefined): AdminRequestAction {
  const raw = url ?? "";
  const queryAt = raw.indexOf("?");
  const pathname = queryAt >= 0 ? raw.slice(0, queryAt) : raw;
  const query = queryAt >= 0 ? raw.slice(queryAt) : "";
  const parts = pathname.split("/");
  // ["", "admin", token, ...rest]
  if (parts[1] !== "admin" || !parts[2]) return { kind: "pass" };
  const token = parts[2];
  const rest = parts.slice(3);
  const isRead = method === "GET" || method === "HEAD";

  if (rest[0] === "files") return { kind: "pass" };

  if (rest[0] === "api") {
    const apiPath = rest.slice(1).join("/");
    const route = API_ROUTES.find((candidate) => candidate.pattern.test(apiPath));
    if (route) {
      if (route.method === "GET" && isRead) return { kind: "pass" };
      if (route.method === method) return { kind: "pass" };
    }
    if (!isRead) return { kind: "notFound" };
    return { kind: "page", token, url: `/admin/${token}${query}` };
  }

  if (!isRead) return { kind: "notFound" };
  return { kind: "page", token };
}
