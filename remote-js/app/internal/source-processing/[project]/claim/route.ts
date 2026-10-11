import { json, notFoundRoute, route } from "../../../../../src/server/http.ts";
import { claimJob } from "../../../../../src/server/sourceProcessingWorker.ts";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ project: string }> };

// POST /internal/source-processing/:project/claim (worker token).
export const POST = route(async (request: Request, context: Context) => {
  const { project } = await context.params;
  return json(await claimJob(request, project));
});

export {
  notFoundRoute as GET,
  notFoundRoute as HEAD,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
