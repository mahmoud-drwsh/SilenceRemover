import { json, notFoundRoute, route } from "../../../../../../src/server/http.ts";
import { failJob } from "../../../../../../src/server/sourceProcessingWorker.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ project: string; jobId: string }> };

// POST /internal/source-processing/:project/:jobId/fail (worker token).
export const POST = route(async (request: Request, context: Context) => {
  const { project, jobId } = await context.params;
  return json(await failJob(request, project, jobId));
});

export {
  notFoundRoute as GET,
  notFoundRoute as HEAD,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
