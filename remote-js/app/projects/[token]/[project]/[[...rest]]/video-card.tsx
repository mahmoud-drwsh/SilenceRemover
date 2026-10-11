"use client";

// The canonical video card: one card for each original (the no-overlay
// video). #57 shows the title, the duration, the size, and the ID.
// Later tickets add to this card: downloads and "Play video" (#58), trash,
// restore, and delete (#59), and the designer upload (#61).

import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDuration, formatMeta, formatSize } from "@/src/client/format";
import type { FileResponse } from "@/src/client/useFileList";
import { VideoTrashActions } from "./trash-actions";
import { VideoCardDownloads } from "./video-card-downloads";
import { DesignerUpload } from "./designer-upload";

type Props = {
  file: FileResponse;
  titleId: string;
  view: string;
  admin: boolean;
  token: string;
  project: string;
  apiBase: string;
  onChanged: () => void;
  /** Announce a finished designer upload and reload the list. */
  onUploaded: (announcement: string) => void;
};

export function VideoCard({ file, titleId, view, admin, token, project, apiBase, onChanged, onUploaded }: Props) {
  const title = file.title || file.id;
  return (
    <Card role="article" aria-labelledby={titleId} data-id={file.id}>
      <CardHeader>
        <CardDescription>Canonical production bundle · Silence removed</CardDescription>
        <CardTitle id={titleId} role="heading" aria-level={2} dir="auto" className="break-words">
          {title}
        </CardTitle>
        <CardDescription className="break-all">
          {formatMeta([formatDuration(file.duration), formatSize(file.file_size), file.id])}
        </CardDescription>
      </CardHeader>
      {view !== "trash" ? (
        <VideoCardDownloads file={file} title={title} token={token} project={project}>
          {file.media_variant === "no-overlay" ? (
            <DesignerUpload
              apiBase={apiBase}
              targetId={file.id}
              title={title}
              hasDesignerVideo={Boolean(file.designer_video_id)}
              onDone={onUploaded}
            />
          ) : null}
          <VideoTrashActions file={file} admin={admin} view={view} apiBase={apiBase} onChanged={onChanged} />
        </VideoCardDownloads>
      ) : admin ? (
        <CardFooter>
          <VideoTrashActions file={file} admin={admin} view={view} apiBase={apiBase} onChanged={onChanged} />
        </CardFooter>
      ) : null}
    </Card>
  );
}
