import { approvePendingAudio } from "../../../../../../../src/server/fileActions.ts";
import { notFound, notFoundRoute, verifyMediaToken } from "../../../../../../../src/server/http.ts";
import { projectRoute } from "../../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

// POST /projects/:token/:project/api/audio/approve-pending (#59).
// Body {confirm: true} -> {ok, approved_count}.
export const POST = projectRoute(async (request, { token, project }) => {
  await verifyMediaToken(token);
  return approvePendingAudio(request, project);
});

// GET and HEAD: token check, then the JSON 404 (old page catch-all).
export const GET = projectRoute(async (_request, { token }) => {
  await verifyMediaToken(token);
  return notFound();
});

export {
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
