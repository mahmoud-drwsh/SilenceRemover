import { json, notFoundRoute, route, verifyMediaToken } from "../../../../../../../../src/server/http.ts";
import { projectApiNotFound } from "../../../../../../../../src/server/projectRoute.ts";
import { completeUpload } from "../../../../../../../../src/server/uploads.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ token: string; project: string; sessionId: string }> };

// POST /projects/:token/:project/api/uploads/:sessionId/complete (media token).
export const POST = route(async (request: Request, context: Context) => {
  const { token, project, sessionId } = await context.params;
  await verifyMediaToken(token);
  return json(await completeUpload(project, sessionId, () => request.json().catch(() => null)));
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
