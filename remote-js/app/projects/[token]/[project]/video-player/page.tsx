import type { Metadata } from "next";
import { unauthorized } from "next/navigation";
import { verifyStoredToken } from "../../../../../src/server/auth.ts";
import { VideoPlayer } from "./video-player";

// The video player page: /projects/<token>/<project>/video-player?file=<id>&title=<title>
// (#58). The server checks the media token before it renders (a bad token
// gives the HTML error page with status 401). The browser streams the video
// from the public stream route. Next.js gives the params URL-decoded.
export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Video Player" };

type Params = { token: string; project: string };
type Search = { file?: string | string[]; title?: string | string[] };

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export default async function VideoPlayerPage({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Search>;
}) {
  const { token, project } = await params;
  if (!(await verifyStoredToken("media", token))) unauthorized();
  const search = await searchParams;
  return (
    <VideoPlayer
      token={token}
      project={project}
      fileId={first(search.file)}
      title={first(search.title) || "Video Player"}
    />
  );
}
