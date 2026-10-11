import { listS3Storage } from "../../../../../../src/server/admin.ts";
import { notFoundRoute } from "../../../../../../src/server/http.ts";

export const dynamic = "force-dynamic";

// GET /admin/:token/api/projects/s3-storage -> S3 bytes of each project.
// Next.js answers HEAD from GET, as Hono did.
export { listS3Storage as GET };

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
