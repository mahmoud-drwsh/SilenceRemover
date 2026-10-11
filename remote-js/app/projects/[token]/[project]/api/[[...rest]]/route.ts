import { notFound, notFoundRoute, verifyMediaToken } from "../../../../../../src/server/http.ts";
import { projectRoute } from "../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

// Unknown paths under /projects/:token/:project/api. A GET checks the media
// token first (401 for a bad token) and then gives the JSON 404, as the old
// page catch-all did for an "api" path. The other methods get the JSON 404
// with no token check. Routes that later tickets add in this folder take
// precedence over this catch-all.
export const GET = projectRoute(async (_request, { token }) => {
  await verifyMediaToken(token);
  return notFound();
});

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
