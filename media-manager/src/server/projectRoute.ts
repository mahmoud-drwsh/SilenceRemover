/**
 * Wrapper for the route handlers under /projects/:token/:project/.
 *
 * - Gives the handler the `token` and `project` (and any other dynamic
 *   segment of the route). Next.js gives them URL-decoded, as the old Hono
 *   router did (verified: "x%2541y" arrives as "x%41y"). Do not decode
 *   them again.
 * - Strict trailing slash, with the old order: a GET (or HEAD) path that ends
 *   with "/" fell to the old page catch-all, which checked the media token
 *   first and then answered 404 for an `api` path. Other methods got the
 *   global 404 with no token check.
 * - Error mapping as in `route()`.
 *
 * The handler checks the media token itself (most routes call
 * `verifyMediaToken`; the snippet-analysis route uses its own 401 text).
 */

import { errorResponse, hasTrailingSlash, notFound, verifyMediaToken } from "./http.ts";

export type ProjectParams = { token: string; project: string };

type Context<P> = { params: Promise<P> };

export function projectRoute<P extends ProjectParams>(
  handler: (request: Request, params: P) => Response | Promise<Response>,
): (request: Request, context: Context<P>) => Promise<Response> {
  return async (request, context) => {
    try {
      const params = await context.params;
      if (hasTrailingSlash(request)) {
        if (request.method === "GET" || request.method === "HEAD") {
          await verifyMediaToken(params.token);
        }
        return notFound();
      }
      return await handler(request, params);
    } catch (err) {
      return errorResponse(err);
    }
  };
}
