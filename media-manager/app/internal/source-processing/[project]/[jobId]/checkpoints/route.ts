import { json, notFoundRoute, route } from "../../../../../../src/server/http.ts";
import { saveCheckpoints } from "../../../../../../src/server/sourceProcessingWorker.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ project: string; jobId: string }> };

// PATCH /internal/source-processing/:project/:jobId/checkpoints (worker token).
export const PATCH = route(async (request: Request, context: Context) => {
  const { project, jobId } = await context.params;
  return json(await saveCheckpoints(request, project, jobId));
});

export {
  notFoundRoute as GET,
  notFoundRoute as HEAD,
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
