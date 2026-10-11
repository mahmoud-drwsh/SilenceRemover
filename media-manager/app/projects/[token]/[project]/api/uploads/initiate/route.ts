import { json, notFound, notFoundRoute, route, verifyMediaToken } from "../../../../../../../src/server/http.ts";
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
