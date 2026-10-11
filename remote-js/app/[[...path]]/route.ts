import { notFoundRoute } from "../../src/server/http.ts";

export const dynamic = "force-dynamic";

// Root catch-all: a path that no other route or page matches gets
// 404 {"detail": "Not Found"} for every method, as in the old service.
// Static and dynamic segments that later tickets add take precedence.
export {
  notFoundRoute as GET,
  notFoundRoute as HEAD,
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
