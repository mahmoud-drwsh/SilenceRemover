"use client";

// The designer upload dialog of a no-overlay card (#61). The card shows the
// button "Upload designer video", or "Upload new revision" when the card
// already has a designer video. The flow is in src/client/designerUpload.ts.

import { useState, type FormEvent } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { uploadDesignerVideo, type DesignerUploadProgress } from "@/src/client/designerUpload";

type Props = {
  apiBase: string;
  targetId: string;
  title: string;
  hasDesignerVideo: boolean;
  /** Called after a successful upload (or `already_uploaded`) with the text to announce. */
  onDone: (announcement: string) => void;
};

export function DesignerUpload({ apiBase, targetId, title, hasDesignerVideo, onDone }: Props) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<DesignerUploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);

  const openChange = (next: boolean) => {
    // While an upload runs, the dialog stays open (Escape, a click outside,
    // Cancel, and the close button do nothing). Thus the progress and an
    // error stay visible.
    if (!next && running) return;
    if (next) {
      setFile(null);
      setProgress(null);
      setError(null);
    }
    setOpen(next);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || !title.trim() || running) return;
    setRunning(true);
    setError(null);
    try {
      const result = await uploadDesignerVideo({ apiBase, targetId, title: title.trim(), file, onProgress: setProgress });
      setOpen(false);
      onDone(result === "already_uploaded" ? "Designer video was already uploaded." : "Designer revision uploaded successfully.");
    } catch (err) {
      setProgress(null);
      setError(err instanceof Error && err.message ? err.message : "Designer upload failed");
    } finally {
      setRunning(false);
    }
  };

  const fileId = `designer-file-${targetId}`;
  const titleId = `designer-title-${targetId}`;
  return (
    <Dialog open={open} onOpenChange={openChange}>
      <DialogTrigger asChild>
        <Button variant="secondary">{hasDesignerVideo ? "Upload new revision" : "Upload designer video"}</Button>
      </DialogTrigger>
      <DialogContent
        showCloseButton={!running}
        onEscapeKeyDown={(event) => { if (running) event.preventDefault(); }}
        onInteractOutside={(event) => { if (running) event.preventDefault(); }}
      >
        <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>Upload designer video</DialogTitle>
            <DialogDescription dir="auto" className="break-words">Saving a new revision for: {title}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor={titleId}>Approved video title</Label>
            <Input id={titleId} value={title} readOnly maxLength={200} dir="auto" />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={fileId}>Redesigned video</Label>
            <Input
              id={fileId}
              type="file"
              accept="video/*"
              required
              disabled={running}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </div>
          {progress ? (
            <div className="flex flex-col gap-2">
              <Progress
                value={progress.total ? Math.round((progress.done / progress.total) * 100) : 0}
                aria-label="Upload progress"
              />
            </div>
          ) : null}
          <div role="status" aria-live="polite" className="text-sm text-muted-foreground">
            {progress?.message ?? ""}
          </div>
          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Upload failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline" disabled={running}>Cancel</Button>
            </DialogClose>
            <Button type="submit" disabled={running}>Upload and link</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
