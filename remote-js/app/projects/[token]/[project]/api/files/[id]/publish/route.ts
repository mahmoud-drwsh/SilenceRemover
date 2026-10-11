import { publishFile } from "../../../../../../../../src/server/fileActions.ts";
import { notFound, notFoundRoute, verifyMediaToken } from "../../../../../../../../src/server/http.ts";
import { projectRoute } from "../../../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

type Params = { token: string; project: string; id: string };

// POST /projects/:token/:project/api/files/:id/publish (#59). No body.
export const POST = projectRoute<Params>(async (_request, { token, project, id }) => {
  await verifyMediaToken(token);
  return publishFile(project, id);
});

// GET and HEAD: token check, then the JSON 404 (old page catch-all).
export const GET = projectRoute<Params>(async (_request, { token }) => {
  await verifyMediaToken(token);
  return notFound();
});

export {
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
