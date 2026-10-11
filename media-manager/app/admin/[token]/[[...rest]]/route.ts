import { adminPageRoute } from "../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// GET /admin/:token, /admin/:token/ and /admin/:token/<any other path>:
// token check, then the admin page. This keeps the old catch-all: an
// unknown GET such as /admin/:token/api/unknown gets the page with 200.
// Phase 2 of #63 replaces the placeholder page with the dashboard.
export { adminPageRoute as GET };

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
