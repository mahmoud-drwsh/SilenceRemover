import { listProjects } from "../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// GET /admin/:token/api/projects -> statistics of each project and the media token.
// Next.js answers HEAD from GET, as Hono did.
export { listProjects as GET };

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
