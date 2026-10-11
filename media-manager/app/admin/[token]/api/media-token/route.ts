import { adminPageRoute, setMediaTokenRoute } from "../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// POST /admin/:token/api/media-token -> store the media token (audit entry).
// GET (and HEAD) serve the admin page after the token check, as the old
// `GET /admin/:token/*` catch-all did.
export { setMediaTokenRoute as POST, adminPageRoute as GET };

export {
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
