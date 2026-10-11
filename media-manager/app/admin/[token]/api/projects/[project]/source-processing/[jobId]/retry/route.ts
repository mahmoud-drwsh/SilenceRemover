import { retrySourceProcessingJob } from "../../../../../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// POST .../source-processing/:jobId/retry -> failed or waiting job to pending, else 409.
// server.ts sends a GET (and a HEAD) of this path to the admin page, as the
// old `GET /admin/:token/*` catch-all did (src/server/adminPaths.ts).
export { retrySourceProcessingJob as POST };

export {
  notFoundRoute as GET,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
