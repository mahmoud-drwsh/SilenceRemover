import { json, notFound, notFoundRoute, route, verifyMediaToken } from "../../../../../../../../src/server/http.ts";
import { completeUpload } from "../../../../../../../../src/server/uploads.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ token: string; project: string; sessionId: string }> };

// POST /projects/:token/:project/api/uploads/:sessionId/complete (media token).
export const POST = route(async (request: Request, context: Context) => {
  const { token, project, sessionId } = await context.params;
  await verifyMediaToken(token);
  return json(await completeUpload(project, sessionId, () => request.json().catch(() => null)));
});

// GET and HEAD: the old project page catch-all checks the token first and
// then answers 404 for an "api" path.
const apiNotFound = route(async (_request: Request, context: { params: Promise<{ token: string }> }) => {
  await verifyMediaToken((await context.params).token);
  return notFound();
});

export {
  apiNotFound as GET,
  apiNotFound as HEAD,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
