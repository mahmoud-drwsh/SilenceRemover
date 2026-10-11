"use client";

// Admin bulk approval on the audio TODO tab (#59): after a confirmation,
// POST /audio/approve-pending {confirm: true}, show the approved count, and
// reload the list.

import { useState } from "react";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { approvePendingAudio, errorText } from "@/src/client/fileApi";
import { ConfirmAction } from "./confirm-action";

export function BulkApprove({ apiBase, onChanged }: { apiBase: string; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ error: boolean; text: string } | null>(null);

  const approve = async () => {
    setBusy(true);
    setResult(null);
    try {
      const count = await approvePendingAudio(apiBase);
      setResult({ error: false, text: `Approved ${count} audio item(s).` });
      onChanged();
    } catch (err) {
      setResult({ error: true, text: `Error: ${errorText(err)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col items-start gap-2">
      <ConfirmAction
        label="Approve pending audio"
        title="Approve all pending audio?"
        description="All non-trashed audio awaiting review will be marked approved. This does not affect trashed audio."
        confirmLabel="Approve all"
        disabled={busy}
        onConfirm={() => void approve()}
      />
      {result ? (
        <Alert variant={result.error ? "destructive" : "default"} data-bulk-result>
          <AlertTitle className="line-clamp-none break-words">{result.text}</AlertTitle>
        </Alert>
      ) : null}
    </div>
  );
}
