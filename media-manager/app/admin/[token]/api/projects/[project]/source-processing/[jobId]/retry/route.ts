import { adminPageRoute, retrySourceProcessingJob } from "../../../../../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// POST .../source-processing/:jobId/retry -> failed or waiting job to pending, else 409.
// GET (and HEAD) serve the admin page after the token check, as the old
// `GET /admin/:token/*` catch-all did.
export { retrySourceProcessingJob as POST, adminPageRoute as GET };

export {
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
