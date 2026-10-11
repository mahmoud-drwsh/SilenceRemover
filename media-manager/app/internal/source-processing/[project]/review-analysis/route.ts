import { notFoundRoute, route } from "../../../../../src/server/http.ts";
import { reviewAnalysisAdapters } from "../../../../../src/server/reviewAnalysisAdapter.ts";

export const dynamic = "force-dynamic";

// POST /internal/source-processing/:project/review-analysis (worker token).
// The multipart body goes straight to the handler (no middleware).
export const POST = route(async (request: Request) => reviewAnalysisAdapters().reviewAnalysis(request));

export {
  notFoundRoute as GET,
  notFoundRoute as HEAD,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
