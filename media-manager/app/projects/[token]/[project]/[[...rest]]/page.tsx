import { unauthorized } from "next/navigation";
import { verifyStoredToken } from "../../../../../src/server/auth.ts";
import { ProjectApp } from "./project-app";

// The project app: /projects/<token>/<project>[/<section>[/<view>]].
// The server checks the media token before it renders (the only database
// read in a page). A bad token gives the HTML error page (app/unauthorized.tsx)
// with status 401. All data comes from the public HTTP API in the browser.
// Next.js gives the params URL-decoded.
export const dynamic = "force-dynamic";

type Params = { token: string; project: string; rest?: string[] };

export default async function ProjectPage({ params }: { params: Promise<Params> }) {
  const { token, project } = await params;
  if (!(await verifyStoredToken("media", token))) unauthorized();
  return <ProjectApp token={token} project={project} />;
}
