import { json, notFoundRoute, route } from "../../src/server/http.ts";

export const dynamic = "force-dynamic";

// GET /healthz -> 200 {"ok": true}. Next.js answers HEAD from GET with no
// body, as Hono did. The other methods get the JSON 404, as before.
export const GET = route(() => json({ ok: true }));

export {
  notFoundRoute as POST,
  notFoundRoute as PUT,
  notFoundRoute as PATCH,
  notFoundRoute as DELETE,
  notFoundRoute as OPTIONS,
};
