"use client";

// Downloads and "Play video" of the canonical video card (#58), as in the old
// frontend/index.html:
//   - Original: GET api/originals/<source_id>/download, then go to the
//     presigned URL. "Unavailable" when the card has no source ID.
//   - Silence Removed: the no-overlay video from the stream route.
//   - Designer Video: the active designer revision from the stream route.
//     "Not uploaded" when there is none.
//   - Play video: the player page in a new tab, or in this tab when the
//     browser blocks the pop-up. window.open keeps window.opener, so the
//     Close button of the player can close the tab.
// The trash view shows none of these (#59 adds the trash actions there).

import { useState, type ReactNode } from "react";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CardContent, CardFooter } from "@/components/ui/card";
import { apiBase, streamUrl } from "@/src/client/projectUrl";
import type { FileResponse } from "@/src/client/useFileList";

type Props = {
  file: FileResponse; title: string; token: string; project: string;
  /** More card actions in the same footer, after "Play video" (as in the old app). */
  children?: ReactNode;
};

function projectBase(token: string, project: string): string {
  return `/projects/${encodeURIComponent(token)}/${encodeURIComponent(project)}`;
}

/** Path of the player page for a video. */
export function playerUrl(token: string, project: string, id: string, title: string): string {
  return `${projectBase(token, project)}/video-player?file=${encodeURIComponent(id)}&title=${encodeURIComponent(title)}`;
}

function Label({ name, note }: { name: string; note: string }) {
  return (
    <span className="flex flex-col items-start leading-tight">
      <span>{name}</span>
      <span className="text-xs font-normal text-muted-foreground">{note}</span>
    </span>
  );
}

export function VideoCardDownloads({ file, title, token, project, children }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sourceId = file.source_id;
  const designerId = file.designer_video_id;

  async function downloadOriginal(id: string) {
    setError(null);
    setBusy(true);
    try {
      const response = await fetch(`${apiBase(token, project)}/originals/${encodeURIComponent(id)}/download`);
      if (!response.ok) throw new Error("Original download unavailable");
      window.location.assign(((await response.json()) as { url: string }).url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function play() {
    const url = playerUrl(token, project, file.id, title);
    const opened = window.open(url, "_blank");
    if (!opened) window.location.href = url;
  }

  return (
    <>
      <CardContent className="flex flex-col gap-2">
        <div role="group" aria-label={`Downloads for ${title}`} className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-2">
          {sourceId ? (
            <Button variant="outline" className="h-auto min-w-0 justify-start whitespace-normal py-2 text-left" disabled={busy}
              onClick={() => void downloadOriginal(sourceId)}>
              <Label name="Original" note="Raw source" />
            </Button>
          ) : (
            <Button variant="outline" className="h-auto min-w-0 justify-start whitespace-normal py-2 text-left" disabled>
              <Label name="Original" note="Unavailable" />
            </Button>
          )}
          <Button variant="outline" className="h-auto min-w-0 justify-start whitespace-normal py-2 text-left" asChild>
            <a href={streamUrl(token, project, file.id, "video")} download>
              <Label name="Silence Removed" note="Video for the designer" />
            </a>
          </Button>
          {designerId ? (
            <Button variant="outline" className="h-auto min-w-0 justify-start whitespace-normal py-2 text-left" asChild>
              <a href={streamUrl(token, project, designerId, "video")} download>
                <Label name="Designer Video" note="Active redesign" />
              </a>
            </Button>
          ) : (
            <Button variant="outline" className="h-auto min-w-0 justify-start whitespace-normal py-2 text-left" disabled>
              <Label name="Designer Video" note="Not uploaded" />
            </Button>
          )}
        </div>
        {error ? (
          <Alert variant="destructive">
            <AlertTitle>{error}</AlertTitle>
          </Alert>
        ) : null}
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        <Button onClick={play}>Play video</Button>
        {children}
      </CardFooter>
    </>
  );
}
