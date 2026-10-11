import { json, notFoundRoute, verifyMediaToken } from "../../../../../../src/server/http.ts";
import { rehearseOriginalRootedBackfill } from "../../../../../../src/server/originalRootedRehearsal.ts";
import { projectRoute } from "../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

// GET /projects/:token/:project/api/original-rooted-rehearsal (#58): a
// report only, with no writes. The other methods get the JSON 404.
export const GET = projectRoute(async (_request, { token, project }) => {
  await verifyMediaToken(token);
  return json(await rehearseOriginalRootedBackfill(project));
});

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
