"use client";

// The review audio card (#59). Rules from the old frontend/index.html:
//   - Inline player (stream route). Only one item plays at a time.
//   - Title field (automatic text direction) with autosave 1000 ms after
//     typing stops: "Typing...", "Saving...", "✓ Saved" (cleared after
//     3000 ms), or "✗ Error: <text>". Autosave keeps the current tags.
//   - Approve (not with an empty title), approved titles are read-only,
//     Reopen, and Discard after a confirmation (also for a non-admin).
//   - Trash view: Restore to TODO and Delete Permanently, for an admin only.

import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { errorText, updateFile } from "@/src/client/fileApi";
import { formatDuration, formatMeta, formatSize } from "@/src/client/format";
import type { FileResponse } from "@/src/client/useFileList";
import { ConfirmAction } from "./confirm-action";
import { TrashActions } from "./trash-actions";

const AUTOSAVE_DELAY_MS = 1000;
const SAVED_CLEAR_MS = 3000;

type Props = {
  file: FileResponse;
  titleId: string;
  view: string;
  admin: boolean;
  token: string;
  project: string;
  apiBase: string;
  onChanged: () => void;
};

type SaveState = { kind: "idle" | "typing" | "saving" | "saved" | "error" | "notice"; text: string };

const IDLE: SaveState = { kind: "idle", text: "" };

function streamUrl(token: string, project: string, id: string): string {
  return `/projects/${encodeURIComponent(token)}/${encodeURIComponent(project)}/stream/${encodeURIComponent(id)}?type=audio`;
}

/** Pause the other players on the page, so that only one item plays. */
function pauseOthers(event: SyntheticEvent<HTMLAudioElement>) {
  for (const player of document.querySelectorAll("audio, video")) {
    if (player !== event.currentTarget) (player as HTMLMediaElement).pause();
  }
}

export function AudioCard({ file, titleId, view, admin, token, project, apiBase, onChanged }: Props) {
  const label = file.title || file.id;
  const approved = file.review_status === "approved";
  const trash = view === "trash";
  const [title, setTitle] = useState(file.title ?? "");
  const [save, setSave] = useState<SaveState>(IDLE);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | null>(null);
  const clearTimer = useRef<number | null>(null);
  // Each edit gets a new number. A save result for an older edit does not
  // change the status.
  const edit = useRef(0);
  const tags = file.tags.length > 0 ? file.tags : ["todo"];

  useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
    if (clearTimer.current) window.clearTimeout(clearTimer.current);
  }, []);

  const cancelAutosave = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
  };

  const autosave = async (value: string, id: number) => {
    setSave({ kind: "saving", text: "Saving..." });
    try {
      await updateFile(apiBase, file.id, "audio", { tags, title: value });
      if (id !== edit.current) return;
      setSave({ kind: "saved", text: "✓ Saved" });
      if (clearTimer.current) window.clearTimeout(clearTimer.current);
      clearTimer.current = window.setTimeout(() => {
        if (id === edit.current) setSave(IDLE);
      }, SAVED_CLEAR_MS);
    } catch (err) {
      if (id === edit.current) setSave({ kind: "error", text: `✗ Error: ${errorText(err)}` });
    }
  };

  const onInput = (value: string) => {
    setTitle(value);
    const id = ++edit.current;
    setSave({ kind: "typing", text: "Typing..." });
    cancelAutosave();
    timer.current = window.setTimeout(() => void autosave(value, id), AUTOSAVE_DELAY_MS);
  };

  const review = async (nextTags: string[]) => {
    const value = title.trim();
    if (!value) {
      setSave({ kind: "notice", text: "Enter a title before approval." });
      return;
    }
    cancelAutosave();
    edit.current++;
    setBusy(true);
    try {
      await updateFile(apiBase, file.id, "audio", { tags: nextTags, title: value });
      onChanged();
    } catch (err) {
      setSave({ kind: "error", text: `✗ Error: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    cancelAutosave();
    edit.current++;
    setBusy(true);
    try {
      await updateFile(apiBase, file.id, "audio", { tags: ["trash"] });
      onChanged();
    } catch (err) {
      setSave({ kind: "error", text: `✗ Error: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

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
          {label}
        </CardTitle>
        <CardDescription>{formatMeta([formatDuration(file.duration), formatSize(file.file_size)])}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <audio
          controls
          preload="none"
          aria-label={`Preview ${label}`}
          className="w-full"
          onPlay={pauseOthers}
        >
          <source src={streamUrl(token, project, file.id)} type={file.mime_type} />
        </audio>
        <Textarea
          dir="auto"
          placeholder="Choose a title..."
          aria-label={`Title for ${label}`}
          value={title}
          readOnly={approved}
          onChange={(event) => onInput(event.target.value)}
        />
        <div
          role="status"
          aria-live="polite"
          data-save-state={save.kind}
          className={
            save.kind === "error" || save.kind === "notice"
              ? "min-h-5 text-sm text-destructive"
              : "min-h-5 text-sm text-muted-foreground"
          }
        >
          {save.text}
        </div>
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        {trash ? (
          admin ? <TrashActions file={file} apiBase={apiBase} onChanged={onChanged} /> : null
        ) : approved ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void review(["todo"])}>
            Reopen review
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={busy} onClick={() => void review(["ready"])}>
              Approve title
            </Button>
            <ConfirmAction
              label="Discard audio"
              title="Discard audio?"
              description="This audio clip is not useful for title review and will be moved to trash."
              confirmLabel="Discard"
              destructive
              disabled={busy}
              onConfirm={() => void discard()}
            />
          </>
        )}
      </CardFooter>
    </Card>
  );
}
