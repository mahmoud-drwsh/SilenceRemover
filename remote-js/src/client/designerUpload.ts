/**
 * The designer upload flow (browser logic, no UI). Same steps, requests, and
 * texts as the old frontend/index.html (submitDesignerUpload):
 *
 *   1. SHA-256 of the whole file in the browser.
 *   2. POST <api>/uploads/initiate with designer_of_id. The server makes a
 *      new revision ID and uses the approved title of the card.
 *   3. Stop early when the server answers `already_uploaded`.
 *   4. PUT each part, one after the other, to the returned URLs. For a
 *      designer session these are the same-origin proxy part URLs (the CSP
 *      does not let the browser connect to S3). Keep the ETag of each part.
 *   5. POST <api>/uploads/<session>/complete with the parts.
 *
 * No npm upload library speaks this JSON protocol (see the #61 PR), so this
 * module is plain fetch. The dialog in designer-upload.tsx shows the
 * progress that `onProgress` gives.
 */

export type DesignerUploadProgress = {
  /** Status text, for example "Uploading 1/3…". */
  message: string;
  /** Parts that are done. */
  done: number;
  /** All parts (0 before the server gives the part URLs). */
  total: number;
};

export type DesignerUploadResult = "uploaded" | "already_uploaded";

type Options = {
  apiBase: string;
  targetId: string;
  title: string;
  file: File;
  onProgress: (progress: DesignerUploadProgress) => void;
};

type Session = {
  already_uploaded?: boolean;
  session_id: string;
  part_size?: number;
  urls?: string[];
  upload_url?: string;
};

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function detail(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" && body.detail ? body.detail : fallback;
}

export async function uploadDesignerVideo({ apiBase, targetId, title, file, onProgress }: Options): Promise<DesignerUploadResult> {
  onProgress({ message: "Preparing secure upload…", done: 0, total: 0 });
  const checksum = await sha256(file);
  const mime = file.type || "video/mp4";
  const initiated = await fetch(`${apiBase}/uploads/initiate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: `${targetId}-designer`, type: "video", title, mime_type: mime,
      file_size: file.size, checksum_sha256: checksum, designer_of_id: targetId,
    }),
  });
  if (!initiated.ok) throw new Error(await detail(initiated, "Could not start designer upload"));
  const session = (await initiated.json()) as Session;
  if (session.already_uploaded) return "already_uploaded";

  const partSize = session.part_size;
  const urls = session.urls ?? (session.upload_url ? [session.upload_url] : []);
  const parts: Array<{ part_number: number; etag: string }> = [];
  for (const [index, url] of urls.entries()) {
    const start = index * (partSize || file.size);
    const part = file.slice(start, Math.min(file.size, start + (partSize || file.size)));
    onProgress({ message: `Uploading ${index + 1}/${urls.length}…`, done: index, total: urls.length });
    const uploaded = await fetch(url, {
      method: "PUT",
      body: part,
      // A single presigned PUT is signed with the Content-Type.
      headers: partSize ? undefined : { "Content-Type": mime },
    });
    if (!uploaded.ok) throw new Error(`Upload part ${index + 1} failed`);
    if (partSize) {
      const etag = uploaded.headers.get("etag");
      if (!etag) throw new Error(`Upload part ${index + 1} did not return an ETag`);
      parts.push({ part_number: index + 1, etag });
    }
  }

  onProgress({ message: "Saving designer revision…", done: urls.length, total: urls.length });
  const completed = await fetch(`${apiBase}/uploads/${encodeURIComponent(session.session_id)}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(partSize ? { parts } : {}),
  });
  if (!completed.ok) throw new Error(await detail(completed, "Could not complete designer upload"));
  return "uploaded";
}
