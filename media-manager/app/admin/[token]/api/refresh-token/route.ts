import { refreshAdminToken } from "../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// POST /admin/:token/api/refresh-token: alias of refresh-admin-token.
// server.ts sends a GET (and a HEAD) of this path to the admin page, as the
// old `GET /admin/:token/*` catch-all did (src/server/adminPaths.ts).
export { refreshAdminToken as POST };

export {
  notFoundRoute as GET,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
