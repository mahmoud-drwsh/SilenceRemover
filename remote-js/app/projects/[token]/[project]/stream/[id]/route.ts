import { notFoundRoute, verifyMediaToken } from "../../../../../../src/server/http.ts";
import { projectRoute } from "../../../../../../src/server/projectRoute.ts";
import { streamFile } from "../../../../../../src/server/stream.ts";

export const dynamic = "force-dynamic";

// GET /projects/:token/:project/stream/:id?type=audio|video|original (#58).
// HEAD uses the same handler; it gives the headers and reads no S3 body.
// The other methods get the JSON 404, as in the old service.
const handler = projectRoute<{ token: string; project: string; id: string }>(
  async (request, { token, project, id }) => {
    await verifyMediaToken(token);
    return streamFile(request, project, id);
  },
);

export {
  handler as GET,
  handler as HEAD,
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
