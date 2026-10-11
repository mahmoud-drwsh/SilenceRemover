import { sourceProcessingStatus } from "../../../../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// GET .../source-processing/status -> job counts and the failed and waiting jobs.
// Next.js answers HEAD from GET, as Hono did.
export { sourceProcessingStatus as GET };

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
