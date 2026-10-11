"use client";

// The review audio card. #57 shows the title, the review state, the
// duration, and the size. #59 adds the player, the title field with
// autosave, and the approve, reopen, discard, and restore actions.

import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDuration, formatMeta, formatSize } from "@/src/client/format";
import type { FileResponse } from "@/src/client/useFileList";

export function AudioCard({ file, titleId }: { file: FileResponse; titleId: string }) {
  const title = file.title || file.id;
  const approved = file.review_status === "approved";
  return (
    <Card role="article" aria-labelledby={titleId} data-id={file.id}>
      <CardHeader>
        <CardDescription>Audio review</CardDescription>
        <CardAction>
          <Badge variant={approved ? "default" : "secondary"}>
            {approved ? "Approved" : "Awaiting title approval"}
          </Badge>
        </CardAction>
        <CardTitle id={titleId} role="heading" aria-level={2} dir="auto" className="break-words">
          {title}
        </CardTitle>
        <CardDescription>{formatMeta([formatDuration(file.duration), formatSize(file.file_size)])}</CardDescription>
      </CardHeader>
    </Card>
  );
}
