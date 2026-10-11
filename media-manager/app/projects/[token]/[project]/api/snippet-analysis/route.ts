import { notFoundRoute, route } from "../../../../../../src/server/http.ts";
import { projectApiNotFound } from "../../../../../../src/server/projectRoute.ts";
import { reviewAnalysisAdapters } from "../../../../../../src/server/reviewAnalysisAdapter.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ token: string; project: string }> };

// POST /projects/:token/:project/api/snippet-analysis (media token, rate limit).
export const POST = route(async (request: Request, context: Context) => {
  const { token, project } = await context.params;
  return reviewAnalysisAdapters().snippetAnalysis(request, token, project);
});

// GET and HEAD: token check first, then the JSON 404 (also with a
// trailing slash), as the old project page catch-all did.
const apiNotFound = projectApiNotFound;

export {
  apiNotFound as GET,
  apiNotFound as HEAD,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
