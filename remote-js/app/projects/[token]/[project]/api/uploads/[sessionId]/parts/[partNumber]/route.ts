import { notFoundRoute, route, verifyMediaToken } from "../../../../../../../../../src/server/http.ts";
import { projectApiNotFound } from "../../../../../../../../../src/server/projectRoute.ts";
import { uploadDesignerPart } from "../../../../../../../../../src/server/uploads.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ token: string; project: string; sessionId: string; partNumber: string }> };

// PUT /projects/:token/:project/api/uploads/:sessionId/parts/:partNumber
// (media token). The designer proxy part route. The handler reads the body
// as a stream; there is no middleware, so no framework body-size limit
// applies. The response has an empty body and the S3 "ETag" header.
export const PUT = route(async (request: Request, context: Context) => {
  const { token, project, sessionId, partNumber } = await context.params;
  await verifyMediaToken(token);
  const etag = await uploadDesignerPart(project, sessionId, partNumber, request.body);
  // "Content-Length: 0" as the old service sent (Next would send the empty
  // body chunked).
  return new Response(null, { status: 200, headers: { ETag: etag, "Content-Length": "0" } });
});

// GET and HEAD: token check first, then the JSON 404 (also with a
// trailing slash), as the old project page catch-all did.
const apiNotFound = projectApiNotFound;

export {
  apiNotFound as GET,
  apiNotFound as HEAD,
  notFoundRoute as POST,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
