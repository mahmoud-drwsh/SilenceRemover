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
import { streamUrl } from "@/src/client/projectUrl";
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
  // The value of the autosave that waits for its timer, or null.
  const pending = useRef<{ value: string; id: number } | null>(null);
  // All PUT requests of this card go through this chain, one after the
  // other. Thus an approval cannot be undone by an autosave that ends late.
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const mounted = useRef(true);
  // Each edit gets a new number. A save result for an older edit does not
  // change the status.
  const edit = useRef(0);
  const tags = file.tags.length > 0 ? file.tags : ["todo"];
  // The latest values, for the unmount cleanup.
  const latest = useRef({ apiBase, id: file.id, tags });
  latest.current = { apiBase, id: file.id, tags };

  /** Send a PUT after the PUT requests that this card sent before. */
  const put = (body: { tags: string[]; title?: string | null }) => {
    const { apiBase: base, id } = latest.current;
    const request = chain.current.catch(() => undefined).then(() => updateFile(base, id, "audio", body));
    chain.current = request;
    return request;
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (clearTimer.current) window.clearTimeout(clearTimer.current);
      // The list can unmount the card (a reload or a tab change) before the
      // autosave timer ends. Send the waiting save now. Do not drop it.
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = null;
      const waiting = pending.current;
      pending.current = null;
      if (waiting) put({ tags: latest.current.tags, title: waiting.value }).catch(() => undefined);
    };
  }, []);

  const cancelAutosave = () => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = null;
    pending.current = null;
  };

  const autosave = async (value: string, id: number) => {
    timer.current = null;
    pending.current = null;
    setSave({ kind: "saving", text: "Saving..." });
    try {
      await put({ tags, title: value });
      if (!mounted.current || id !== edit.current) return;
      setSave({ kind: "saved", text: "✓ Saved" });
      if (clearTimer.current) window.clearTimeout(clearTimer.current);
      clearTimer.current = window.setTimeout(() => {
        if (id === edit.current) setSave(IDLE);
      }, SAVED_CLEAR_MS);
    } catch (err) {
      if (mounted.current && id === edit.current) setSave({ kind: "error", text: `✗ Error: ${errorText(err)}` });
    }
  };

  const onInput = (value: string) => {
    setTitle(value);
    const id = ++edit.current;
    setSave({ kind: "typing", text: "Typing..." });
    cancelAutosave();
    pending.current = { value, id };
    timer.current = window.setTimeout(() => void autosave(value, id), AUTOSAVE_DELAY_MS);
  };

  /** A review PUT (approve, reopen or discard). It waits for the earlier PUT requests. */
  const send = async (body: { tags: string[]; title?: string | null }) => {
    cancelAutosave();
    edit.current++;
    setBusy(true);
    try {
      await put(body);
      onChanged();
    } catch (err) {
      if (mounted.current) setSave({ kind: "error", text: `✗ Error: ${errorText(err)}` });
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const review = async (nextTags: string[]) => {
    const value = title.trim();
    if (!value) {
      setSave({ kind: "notice", text: "Enter a title before approval." });
      return;
    }
    await send({ tags: nextTags, title: value });
  };

  const discard = () => send({ tags: ["trash"] });

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
          <source src={streamUrl(token, project, file.id, "audio")} type={file.mime_type} />
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
