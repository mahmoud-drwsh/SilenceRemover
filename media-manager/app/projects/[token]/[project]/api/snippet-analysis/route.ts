import { notFound, notFoundRoute, route, verifyMediaToken } from "../../../../../../src/server/http.ts";
import { reviewAnalysisAdapters } from "../../../../../../src/server/reviewAnalysisAdapter.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ token: string; project: string }> };

// POST /projects/:token/:project/api/snippet-analysis (media token, rate limit).
export const POST = route(async (request: Request, context: Context) => {
  const { token, project } = await context.params;
  return reviewAnalysisAdapters().snippetAnalysis(request, token, project);
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
