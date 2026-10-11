/**
 * Browser calls for the file actions (#59). No UI. On an error response
 * each function throws an Error with the response text, as the old app
 * showed it ("Error: <text>").
 */

export type MediaType = "audio" | "video" | "original";

async function send(url: string, init: RequestInit): Promise<unknown> {
  const res = await fetch(url, { ...init, cache: "no-store" });
  const text = await res.text();
  if (!res.ok) throw new Error(text || `HTTP ${res.status}: ${res.statusText}`);
  return text ? JSON.parse(text) : null;
}

function fileUrl(apiBase: string, id: string, type: MediaType): string {
  return `${apiBase}/files/${encodeURIComponent(id)}?type=${type}`;
}

/** PUT /files/<id>?type=<type> with {tags, title?}. */
export function updateFile(
  apiBase: string,
  id: string,
  type: MediaType,
  body: { tags: string[]; title?: string | null },
): Promise<unknown> {
  return send(fileUrl(apiBase, id, type), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** DELETE /files/<id>?type=<type> (only for a trashed file). */
export function deleteFile(apiBase: string, id: string, type: MediaType): Promise<unknown> {
  return send(fileUrl(apiBase, id, type), { method: "DELETE" });
}

/** POST /audio/approve-pending with {confirm: true}. Gives the approved count. */
export async function approvePendingAudio(apiBase: string): Promise<number> {
  const body = (await send(`${apiBase}/audio/approve-pending`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: true }),
  })) as { approved_count: number };
  return body.approved_count;
}

/** The text of an error for the UI. */
export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
