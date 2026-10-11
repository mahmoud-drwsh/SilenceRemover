import { notFoundRoute, verifyMediaToken } from "../../../../../../../../src/server/http.ts";
import { originalDerived } from "../../../../../../../../src/server/originals.ts";
import { projectRoute } from "../../../../../../../../src/server/projectRoute.ts";

export const dynamic = "force-dynamic";

// GET /projects/:token/:project/api/originals/:id/derived (#58): the raw rows
// that have this original as source_id. The other methods get the JSON 404.
export const GET = projectRoute<{ token: string; project: string; id: string }>(
  async (_request, { token, project, id }) => {
    await verifyMediaToken(token);
    return originalDerived(project, id);
  },
);

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
