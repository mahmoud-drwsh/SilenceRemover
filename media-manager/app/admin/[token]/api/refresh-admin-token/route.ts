import { adminPageRoute, refreshAdminToken } from "../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// POST /admin/:token/api/refresh-admin-token -> new admin token (audit entry).
// GET (and HEAD) serve the admin page after the token check, as the old
// `GET /admin/:token/*` catch-all did.
export { refreshAdminToken as POST, adminPageRoute as GET };

export {
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
