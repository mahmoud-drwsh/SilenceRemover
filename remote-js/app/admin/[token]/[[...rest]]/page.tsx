import type { Metadata } from "next";
import { headers } from "next/headers";
import { unauthorized } from "next/navigation";
import { clientIpFromHeaders } from "../../../../src/server/clientIp.ts";
import { checkAdminToken } from "../../../../src/server/http.ts";
import { AdminDashboard } from "./admin-dashboard";

// The admin dashboard: GET /admin/<token>, /admin/<token>/ and the other
// GET paths that the old catch-all served (src/server/adminPaths.ts).
// server.ts applies the admin-token rate limit first (JSON 429 with
// Retry-After). Here the server checks the token before it renders: a bad
// token counts as a failed attempt and gives the HTML error page
// (app/admin/unauthorized.tsx) with status 401. A good token clears the
// counter. All data comes from the public admin API in the browser.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Media Manager Admin" };

type Params = { token: string; rest?: string[] };

export default async function AdminPage({ params }: { params: Promise<Params> }) {
  const { token } = await params;
  const clientIp = clientIpFromHeaders(await headers());
  if ((await checkAdminToken(clientIp, token)) !== "ok") unauthorized();
  return <AdminDashboard initialToken={token} />;
}
