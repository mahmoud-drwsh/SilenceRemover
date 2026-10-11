import { listFiles } from "../../../../../../src/server/fileList.ts";
import { notFoundRoute, verifyMediaToken } from "../../../../../../src/server/http.ts";
import { projectRoute } from "../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

// GET /projects/:token/:project/api/files - the file list (#57).
// Next.js answers HEAD from GET. The other methods get the JSON 404, as in
// the old service (the old POST upload route is removed).
export const GET = projectRoute(async (request, { token, project }) => {
  await verifyMediaToken(token);
  return listFiles(project, new URL(request.url));
});

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
