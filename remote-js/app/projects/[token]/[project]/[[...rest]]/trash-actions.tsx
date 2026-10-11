"use client";

// Trash actions of a card (#59): move a video to Trash, restore from Trash
// (audio to TODO, video to All), and permanent delete. Each action asks for
// a confirmation, then reloads the list. An error shows "Error: <text>".

import { useState } from "react";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { deleteFile, errorText, updateFile } from "@/src/client/fileApi";
import type { FileResponse } from "@/src/client/useFileList";
import { ConfirmAction } from "./confirm-action";

/** Run a card action: busy flag, error text, and a list reload on success. */
export function useCardAction(onChanged: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

export function ActionError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <Alert variant="destructive">
      <AlertTitle className="line-clamp-none break-words">Error: {error}</AlertTitle>
    </Alert>
  );
}

type Props = { file: FileResponse; apiBase: string; onChanged: () => void };

function displayTitle(file: FileResponse): string {
  return file.title || file.id;
}

/** Restore and Delete Permanently, for a card in the Trash view. */
export function TrashActions({ file, apiBase, onChanged }: Props) {
  const { busy, error, run } = useCardAction(onChanged);
  const audio = file.type === "audio";
  const title = displayTitle(file);
  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <ConfirmAction
          label={audio ? "Restore to TODO" : "Restore to All"}
          title="Restore from Trash?"
          description={`"${title}" will be restored.`}
          confirmLabel="Restore"
          disabled={busy}
          onConfirm={() => void run(() => updateFile(apiBase, file.id, file.type, { tags: audio ? ["todo"] : [] }))}
        />
        <ConfirmAction
          label="Delete Permanently"
          title="Delete Permanently?"
          description={`"${title}" will be permanently deleted. This cannot be undone.`}
          confirmLabel="Delete Permanently"
          destructive
          disabled={busy}
          onConfirm={() => void run(() => deleteFile(apiBase, file.id, file.type))}
        />
      </div>
      <ActionError error={error} />
    </div>
  );
}

/** Move to Trash, for a video card outside the Trash view. */
export function MoveToTrash({ file, apiBase, onChanged }: Props) {
  const { busy, error, run } = useCardAction(onChanged);
  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <ConfirmAction
          label="Move to Trash"
          title="Move to Trash?"
          description="This file will be moved to trash. You can restore it later."
          confirmLabel="Move to Trash"
          destructive
          disabled={busy}
          onConfirm={() => void run(() => updateFile(apiBase, file.id, file.type, { tags: ["trash"] }))}
        />
      </div>
      <ActionError error={error} />
    </div>
  );
}

/** The admin trash actions of a video card: Move to Trash, or Restore and Delete in the Trash view. */
export function VideoTrashActions({ admin, view, ...props }: Props & { admin: boolean; view: string }) {
  if (!admin) return null;
  return view === "trash" ? <TrashActions {...props} /> : <MoveToTrash {...props} />;
}
