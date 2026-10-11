import { deleteFile, updateFile } from "../../../../../../../src/server/fileActions.ts";
import { notFound, notFoundRoute, verifyMediaToken } from "../../../../../../../src/server/http.ts";
import { projectRoute } from "../../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

type Params = { token: string; project: string; id: string };

// PUT /projects/:token/:project/api/files/:id?type=... - tags and title (#59).
export const PUT = projectRoute<Params>(async (request, { token, project, id }) => {
  await verifyMediaToken(token);
  return updateFile(request, project, id);
});

// DELETE /projects/:token/:project/api/files/:id?type=... - only trashed files (#59).
export const DELETE = projectRoute<Params>(async (request, { token, project, id }) => {
  await verifyMediaToken(token);
  return deleteFile(request, project, id);
});

// GET and HEAD: the old page catch-all checks the token first and then
// answers 404 for an "api" path. Next.js answers HEAD from GET.
export const GET = projectRoute<Params>(async (_request, { token }) => {
  await verifyMediaToken(token);
  return notFound();
});

export {
  notFoundRoute as POST,
  notFoundRoute as PATCH,
  notFoundRoute as OPTIONS,
};
