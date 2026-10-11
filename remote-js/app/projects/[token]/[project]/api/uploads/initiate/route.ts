import { json, notFoundRoute, route, verifyMediaToken } from "../../../../../../../src/server/http.ts";
import { projectApiNotFound } from "../../../../../../../src/server/projectRoute.ts";
import { initiateUpload } from "../../../../../../../src/server/uploads.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ token: string; project: string }> };

// POST /projects/:token/:project/api/uploads/initiate (media token).
export const POST = route(async (request: Request, context: Context) => {
  const { token, project } = await context.params;
  await verifyMediaToken(token);
  const body = await request.json().catch(() => null);
  return json(await initiateUpload(token, project, body));
});

// GET and HEAD: token check first, then the JSON 404 (also with a
// trailing slash), as the old project page catch-all did.
const apiNotFound = projectApiNotFound;

export {
  apiNotFound as GET,
  apiNotFound as HEAD,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
