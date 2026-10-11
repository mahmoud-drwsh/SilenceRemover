/**
 * Upload sessions for pipeline media (#60). The behavior is the same as in
 * remote-js/src/routes/uploads.ts. The route handlers in
 * app/projects/[token]/[project]/api/uploads/ check the media token and call
 * these functions.
 *
 * - initiateUpload: one presigned PUT (small audio) or a presigned multipart
 *   upload (8 MiB parts, 15 min URLs). A designer session (designer_of_id)
 *   gets relative same-origin part URLs.
 * - uploadDesignerPart: the designer proxy part route
 *   (PUT .../uploads/:sessionId/parts/:partNumber, #61). It streams the
 *   request body and keeps at most one part (8 MiB) in memory.
 * - completeUpload: verify size and SHA-256 (with retries), sniff the MIME
 *   type, probe the duration, commit the metadata, and queue originals for
 *   source processing.
 * - abortUpload: abort the S3 multipart upload and mark the session aborted.
 * - cleanupExpiredUploadSessions: startup cleanup of expired sessions.
 */

import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getDb, schemaIdent } from "./db.ts";
import { probeDurationSeconds } from "./ffprobe.ts";
import {
  assertSourceOriginalExists, commitUploadMetadata, parseUploadTags, resolveUploadOverwrite,
} from "./fileMetadata.ts";
import { ALLOWED_MIME, AUDIO_MIME, VIDEO_MIME, getExtensionForMime, sniffMimeFromFile } from "./mime.ts";
import { HttpError, type FileType } from "./schemas.ts";
import { sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import { enqueueSourceProcessing } from "./sourceProcessing.ts";
import {
  MULTIPART_PART_SIZE, abortMultipartUpload, completeMultipartUpload, createMultipartUpload,
  presignPutObject, presignUploadPart, storageGet, uploadMultipartPart,
} from "./storage.ts";
import { videoVariantSql, visibilitySql } from "./videoSql.ts";

export { MULTIPART_PART_SIZE };
export const SESSION_TTL_MS = 24 * 60 * 60 * 1000;
export const MAX_PARTS = 10_000;
const COMPLETION_VERIFY_DELAYS_MS = [0, 500, 1_500, 3_000];

export type UploadSession = {
  id: string; project: string; file_id: string; type: FileType; mime_type: string;
  file_size: number; checksum_sha256: string; title: string; tags: unknown;
  source_id: string | null; original_filename: string | null; upload_id: string | null;
  designer_of_id: string | null;
  media_variant: "pipeline-final" | "no-overlay" | "designer" | null;
  visibility: "active" | "trash" | null;
  publication_status: "pending" | "published" | null;
  expires_at: string | Date; state: "active" | "completed" | "aborted";
};

type InitiateInput = {
  id: string; type: FileType; mime: string; size: number; checksum: string; title: string;
  tags: string[]; sourceId: string | null; filename: string | null; designerOfId: string | null;
  mediaVariant: "no-overlay" | "designer" | null; visibility: "active" | "trash" | null;
  publicationStatus: "pending" | "published" | null;
};

function checksum(value: unknown): string {
  const result = String(value ?? "").toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(result)) throw new HttpError(400, "checksum_sha256 must be a SHA-256 hex digest");
  return result;
}

function parseBody(body: unknown): InitiateInput {
  if (!body || typeof body !== "object") throw new HttpError(400, "JSON body is required");
  const data = body as Record<string, unknown>;
  const type = data.type;
  // The subtitle type is removed (#44).
  if (type !== "audio" && type !== "video" && type !== "original") throw new HttpError(400, "Invalid type");
  const id = sanitizeFileId(String(data.id ?? ""));
  const mime = String(data.mime_type ?? "");
  const size = Number(data.file_size);
  if (!id || !ALLOWED_MIME.has(mime) || (type === "original" && !VIDEO_MIME.has(mime))) throw new HttpError(400, "Invalid media identity or MIME type");
  if (!Number.isSafeInteger(size) || size <= 0) throw new HttpError(400, "file_size must be a positive integer");
  const sourceIdRaw = data.source_id == null ? "" : String(data.source_id);
  const sourceId = sourceIdRaw ? sanitizeFileId(sourceIdRaw) : null;
  if (sourceIdRaw && !sourceId) throw new HttpError(400, "Invalid source_id");
  const filename = type === "original" ? sanitizeFilename(String(data.original_filename ?? "")) : null;
  if (type === "original" && !filename) throw new HttpError(400, "original_filename is required");
  const tagValue = JSON.stringify(data.tags ?? (type === "audio" ? ["todo"] : []));
  const designerOfIdRaw = data.designer_of_id == null ? "" : String(data.designer_of_id);
  const designerOfId = designerOfIdRaw ? sanitizeFileId(designerOfIdRaw) : null;
  if (designerOfIdRaw && !designerOfId) throw new HttpError(400, "Invalid designer_of_id");
  if (designerOfId && type !== "video") throw new HttpError(400, "Designer uploads must be videos");
  const mediaVariant = data.media_variant == null ? null : String(data.media_variant);
  const visibility = data.visibility == null ? null : String(data.visibility);
  const publicationStatus = data.publication_status == null ? null : String(data.publication_status);
  // New uploads cannot use the removed pipeline-final variant (#44). Old rows
  // can still have it, so the read side keeps the value.
  if (mediaVariant !== null && !["no-overlay", "designer"].includes(mediaVariant)) throw new HttpError(400, "Invalid media_variant");
  if (visibility !== null && visibility !== "active" && visibility !== "trash") throw new HttpError(400, "Invalid visibility");
  if (publicationStatus !== null && publicationStatus !== "pending" && publicationStatus !== "published") throw new HttpError(400, "Invalid publication_status");
  if (type === "video" && !designerOfId && (!mediaVariant || !visibility || !publicationStatus)) throw new HttpError(400, "Video uploads require explicit media_variant, visibility, and publication_status");
  if (type !== "video" && (mediaVariant !== null || publicationStatus !== null)) throw new HttpError(400, "Video media attributes are only valid for video uploads");
  return {
    id, type, mime, size, checksum: checksum(data.checksum_sha256), title: String(data.title ?? ""),
    tags: parseUploadTags(tagValue, type), sourceId, filename, designerOfId,
    mediaVariant: mediaVariant as "no-overlay" | "designer" | null,
    visibility: visibility as "active" | "trash" | null,
    publicationStatus: publicationStatus as "pending" | "published" | null,
  };
}

async function resolveDesignerTarget(project: string, targetId: string): Promise<{ id: string; sourceId: string; title: string }> {
  const sql = getDb(); const ident = schemaIdent();
  // The no-overlay video is the only designer target (#44). The revision
  // inherits the approved title of its card, not a variant title.
  const target = (await sql.unsafe<{ id: string; source_id: string | null; title: string | null; media_variant: string | null; visibility: string }[]>(
    `SELECT designer_target.id, designer_target.source_id, designer_target.title,
            ${videoVariantSql("designer_target")} AS media_variant,
            ${visibilitySql("designer_target")} AS visibility
       FROM ${ident}.files AS designer_target
      WHERE designer_target.id = $1 AND designer_target.project = $2 AND designer_target.type = 'video'
        AND designer_target.designer_of_id IS NULL AND designer_target.id NOT LIKE '%-designer'`,
    [targetId, project],
  ))[0];
  if (!target || !target.source_id || target.media_variant !== "no-overlay" || target.visibility !== "active") {
    throw new HttpError(400, "designer_of_id must select an available no-overlay video in this project");
  }
  return { id: target.id, sourceId: target.source_id, title: target.title?.trim() || target.id };
}

async function hasCommittedVideo(project: string, fileId: string): Promise<boolean> {
  const sql = getDb(); const ident = schemaIdent();
  return (await sql.unsafe<{ id: string }[]>(
    `SELECT id FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = 'video'`, [fileId, project],
  )).length > 0;
}

function partsJson(body: unknown): Array<{ partNumber: number; etag: string }> {
  const parts = (body as Record<string, unknown> | null)?.parts;
  if (!Array.isArray(parts)) return [];
  return parts.map((part) => ({ partNumber: Number((part as Record<string, unknown>).part_number), etag: String((part as Record<string, unknown>).etag ?? "") }));
}

function sessionTags(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

/** False when the session is not active or its 24 h expiry is in the past. */
export function isSessionActive(session: UploadSession): boolean {
  return session.state === "active" && new Date(session.expires_at).getTime() >= Date.now();
}

/** Number of multipart parts for a size (8 MiB parts). */
export function partCountForSize(size: number): number {
  return Math.ceil(size / MULTIPART_PART_SIZE);
}

async function downloadAndVerifyCompletedObject(session: UploadSession, ext: string, tempPath: string): Promise<void> {
  let problem = "object was not available";
  let lastError: unknown;
  for (const [attempt, delay] of COMPLETION_VERIFY_DELAYS_MS.entries()) {
    if (delay) await wait(delay);
    const hash = createHash("sha256");
    let bytes = 0;
    try {
      const handle = await open(tempPath, "w");
      try {
        const reader = (await storageGet(session.type, session.project, session.file_id, ext, null)).getReader();
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            bytes += value.byteLength;
            hash.update(value);
            await handle.write(value);
          }
        } finally { reader.releaseLock(); }
      } finally { await handle.close(); }
      if (bytes !== Number(session.file_size)) {
        problem = `expected ${session.file_size} bytes, got ${bytes}`;
      } else if (hash.digest("hex") !== session.checksum_sha256) {
        problem = "object checksum did not match request";
      } else {
        return;
      }
      lastError = undefined;
    } catch (error) {
      lastError = error;
      problem = error instanceof Error ? error.message : String(error);
    }
    if (attempt < COMPLETION_VERIFY_DELAYS_MS.length - 1) {
      console.warn(`UPLOAD_VERIFY_RETRY id=${JSON.stringify(session.file_id)} project=${JSON.stringify(session.project)} attempt=${attempt + 1} reason=${JSON.stringify(problem)}`);
    }
  }
  if (lastError) throw lastError;
  throw new HttpError(400, `Uploaded object verification failed: ${problem}`);
}

/** The upload session with this ID in this project, if any. */
export async function sessionById(project: string, id: string): Promise<UploadSession | undefined> {
  const sql = getDb(); const ident = schemaIdent();
  return (await sql.unsafe<UploadSession[]>(`SELECT * FROM ${ident}.upload_sessions WHERE id = $1 AND project = $2`, [id, project]))[0];
}

async function sessionResponse(session: UploadSession, partCount: number, token: string): Promise<Record<string, unknown>> {
  const ext = getExtensionForMime(session.mime_type);
  if (!session.upload_id) return { ok: true, session_id: session.id, id: session.file_id, type: session.type, upload_url: await presignPutObject(session.type, session.project, session.file_id, ext, session.mime_type) };
  if (session.designer_of_id) {
    // The browser cannot PUT to S3 (CSP connect-src 'self'), so a designer
    // session sends its parts through the same-origin part route (#61).
    const base = `/projects/${encodeURIComponent(token)}/${encodeURIComponent(session.project)}/api/uploads/${encodeURIComponent(session.id)}/parts`;
    return {
      ok: true, session_id: session.id, id: session.file_id, type: session.type,
      upload_id: session.upload_id, part_size: MULTIPART_PART_SIZE,
      urls: Array.from({ length: partCount }, (_, index) => `${base}/${index + 1}`),
    };
  }
  const urls = await Promise.all(Array.from({ length: partCount }, (_, index) => presignUploadPart(session.type, session.project, session.file_id, ext, session.upload_id!, index + 1)));
  return { ok: true, session_id: session.id, id: session.file_id, type: session.type, upload_id: session.upload_id, part_size: MULTIPART_PART_SIZE, urls };
}

/** POST /projects/:token/:project/api/uploads/initiate (token already checked). */
export async function initiateUpload(token: string, project: string, body: unknown): Promise<Record<string, unknown>> {
  let input = parseBody(body);
  if (input.designerOfId) {
    const target = await resolveDesignerTarget(project, input.designerOfId);
    input = {
      ...input,
      // A designer upload is a retained revision, never a replacement of the
      // deterministic legacy `${target.id}-designer` object.
      id: `${target.id}-designer-${randomUUID()}`,
      sourceId: target.sourceId,
      // A designer revision inherits the approved title of its no-overlay
      // card; its presentation variant is not part of the media title.
      title: target.title,
      tags: [],
      designerOfId: target.id,
      mediaVariant: "designer",
      visibility: "active",
      publicationStatus: "published",
    };
  }
  if (input.type !== "original") await assertSourceOriginalExists(project, input.sourceId);
  const sql = getDb(); const ident = schemaIdent();
  const existing = (await sql.unsafe<UploadSession[]>(
    `SELECT * FROM ${ident}.upload_sessions WHERE project=$1 AND file_id=$2 AND type=$3 AND checksum_sha256=$4 AND state='active' AND expires_at > now() ORDER BY created_at DESC LIMIT 1`,
    [project, input.id, input.type, input.checksum],
  ))[0];
  const committed = (await sql.unsafe<{ checksum_sha256: string | null }[]>(
    `SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`, [project, input.id, input.type],
  ))[0];
  if (input.type === "original" && committed?.checksum_sha256 === input.checksum) {
    await enqueueSourceProcessing(project, input.id, input.checksum);
    return { ok: true, id: input.id, type: input.type, already_uploaded: true };
  }
  if (input.type === "original" && committed) {
    throw new HttpError(409, `Original '${input.id}' already exists with different bytes`);
  }
  const partCount = input.type === "audio" && input.size <= MULTIPART_PART_SIZE ? 0 : partCountForSize(input.size);
  if (partCount > MAX_PARTS) throw new HttpError(413, "Upload exceeds multipart upload part limit");
  const overwritten = input.designerOfId
    ? await hasCommittedVideo(project, input.id)
    : await resolveUploadOverwrite(input.id, project, input.type, input.title).catch((error) => {
      if (existing) return false;
      throw error;
    });
  if (existing) {
    // Resume with the caller's current explicit lifecycle contract. This also
    // sanitizes an active session created by a pre-migration client.
    await sql.unsafe(
      `UPDATE ${ident}.upload_sessions
          SET tags=$1::jsonb, media_variant=$2, visibility=$3, publication_status=$4
        WHERE id=$5`,
      [JSON.stringify(input.tags), input.mediaVariant, input.visibility, input.publicationStatus, existing.id],
    );
    return sessionResponse(existing, partCount, token);
  }
  const ext = getExtensionForMime(input.mime);
  const uploadId = partCount ? await createMultipartUpload(input.type, project, input.id, ext, input.mime) : null;
  const session: UploadSession = {
    id: randomUUID(), project, file_id: input.id, type: input.type, mime_type: input.mime, file_size: input.size,
    checksum_sha256: input.checksum, title: input.title, tags: input.tags, source_id: input.sourceId,
    original_filename: input.filename, upload_id: uploadId, designer_of_id: input.designerOfId,
    media_variant: input.mediaVariant, visibility: input.visibility, publication_status: input.publicationStatus,
    expires_at: new Date(Date.now() + SESSION_TTL_MS), state: "active",
  };
  await sql.unsafe(`INSERT INTO ${ident}.upload_sessions (id,project,file_id,type,mime_type,file_size,checksum_sha256,title,tags,source_id,original_filename,upload_id,designer_of_id,media_variant,visibility,publication_status,expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13,$14,$15,$16,$17)`,
    [session.id, project, input.id, input.type, input.mime, input.size, input.checksum, input.title, JSON.stringify(input.tags), input.sourceId, input.filename, uploadId, input.designerOfId, input.mediaVariant, input.visibility, input.publicationStatus, session.expires_at]);
  return { ...(await sessionResponse(session, partCount, token)), overwritten };
}

/**
 * POST /projects/:token/:project/api/uploads/:sessionId/complete (token
 * already checked). `readBody` reads the JSON body; the function calls it
 * only for a multipart session, as the old route did. A failure leaves the
 * session active, so that the client can try again.
 */
export async function completeUpload(project: string, sessionId: string, readBody: () => Promise<unknown>): Promise<Record<string, unknown>> {
  const session = await sessionById(project, sessionId);
  if (!session) throw new HttpError(404, "Upload session not found");
  if (session.state === "completed") {
    if (session.type === "original") await enqueueSourceProcessing(project, session.file_id, session.checksum_sha256);
    return { ok: true, id: session.file_id, type: session.type, already_completed: true };
  }
  if (!isSessionActive(session)) throw new HttpError(409, "Upload session is no longer active");
  // An old session can still have a removed type or variant (#44).
  if (!["audio", "video", "original"].includes(String(session.type)) || String(session.media_variant) === "pipeline-final") {
    throw new HttpError(400, "Upload session uses a removed media type or variant");
  }
  const sql = getDb(); const ident = schemaIdent();
  if (session.type === "original") {
    const committed = (await sql.unsafe<{ checksum_sha256: string | null }[]>(
      `SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='original'`,
      [project, session.file_id],
    ))[0];
    if (committed?.checksum_sha256 === session.checksum_sha256) {
      await enqueueSourceProcessing(project, session.file_id, session.checksum_sha256);
      await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='completed' WHERE id=$1`, [session.id]);
      return { ok: true, id: session.file_id, type: session.type, already_completed: true };
    }
  }
  const ext = getExtensionForMime(session.mime_type);
  if (session.upload_id) {
    const parts = partsJson(await readBody());
    if (!parts.length || parts.some((part) => !Number.isInteger(part.partNumber) || part.partNumber < 1 || !part.etag)) throw new HttpError(400, "Completed multipart ETags are required");
    await completeMultipartUpload(session.type, project, session.file_id, ext, session.upload_id, parts);
  }
  const tempDir = join(tmpdir(), `media-manager-${session.id}`);
  await mkdir(tempDir, { recursive: true });
  const tempPath = join(tempDir, `upload${ext}`);
  let overwritten = false;
  try {
    await downloadAndVerifyCompletedObject(session, ext, tempPath);
    const detected = await sniffMimeFromFile(tempPath);
    const allowedDetectedMime = session.type === "audio" ? AUDIO_MIME : VIDEO_MIME;
    if (!detected || !allowedDetectedMime.has(detected)) throw new HttpError(400, `Uploaded object MIME type is invalid: expected ${session.type}, got ${detected ?? "unknown"}`);
    const duration = await probeDurationSeconds(tempPath);
    overwritten = await resolveUploadOverwrite(session.file_id, project, session.type, session.title);
    await commitUploadMetadata({
      fileId: session.file_id, project, fileType: session.type,
      title: session.type === "original" ? session.original_filename ?? session.file_id : session.title,
      tagList: sessionTags(session.tags), duration, fileSize: Number(session.file_size),
      mime: session.mime_type, overwritten, sourceId: session.source_id,
      originalFilename: session.original_filename, checksumSha256: session.checksum_sha256,
      designerOfId: session.designer_of_id,
      attributes: {
        ...(session.media_variant ? { mediaVariant: session.media_variant } : {}),
        ...(session.visibility ? { visibility: session.visibility } : {}),
        ...(session.publication_status ? { publicationStatus: session.publication_status } : {}),
      },
    });
    if (session.type === "original") await enqueueSourceProcessing(project, session.file_id, session.checksum_sha256);
    await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='completed' WHERE id=$1`, [session.id]);
  } finally { await rm(tempDir, { recursive: true, force: true }); }
  return { ok: true, id: session.file_id, type: session.type, overwritten };
}

/**
 * Read a request body stream. Keep the bytes up to `limit` and count (but do
 * not keep) the bytes after it. Thus the memory use stays at one part, and
 * the caller can still compare the full body size with the part size. The
 * function reads the full body, as the old service did, before it answers.
 */
async function readBoundedBody(body: ReadableStream<Uint8Array> | null, limit: number): Promise<{ bytes: Uint8Array; total: number }> {
  const bytes = new Uint8Array(limit);
  let total = 0;
  if (!body) return { bytes: bytes.subarray(0, 0), total };
  const reader = body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (total < limit) bytes.set(value.subarray(0, limit - total), total);
      total += value.byteLength;
    }
  } finally { reader.releaseLock(); }
  return { bytes: bytes.subarray(0, Math.min(total, limit)), total };
}

/**
 * PUT /projects/:token/:project/api/uploads/:sessionId/parts/:partNumber
 * (token already checked). The browser cannot PUT to S3 (CSP connect-src
 * 'self'), so the app sends each designer part to S3. Same checks, order,
 * and texts as remote-js/src/routes/uploads.ts. Returns the S3 ETag (with
 * its quotes).
 */
export async function uploadDesignerPart(
  project: string, sessionId: string, partNumberRaw: string, body: ReadableStream<Uint8Array> | null,
): Promise<string> {
  const session = await sessionById(project, sessionId);
  const partNumber = Number(partNumberRaw);
  const partCount = session ? partCountForSize(Number(session.file_size)) : 0;
  if (!session || !session.designer_of_id || !session.upload_id) throw new HttpError(404, "Designer upload session not found");
  if (!isSessionActive(session)) throw new HttpError(409, "Upload session is no longer active");
  if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > partCount) throw new HttpError(400, "Invalid upload part number");
  const expectedSize = partNumber < partCount
    ? MULTIPART_PART_SIZE
    : Number(session.file_size) - MULTIPART_PART_SIZE * (partCount - 1);
  const { bytes, total } = await readBoundedBody(body, expectedSize);
  if (total !== expectedSize) throw new HttpError(400, `Upload part must contain exactly ${expectedSize} bytes`);
  return uploadMultipartPart(
    session.type, project, session.file_id, getExtensionForMime(session.mime_type),
    session.upload_id, partNumber, bytes,
  );
}

/** POST /projects/:token/:project/api/uploads/:sessionId/abort (token already checked). */
export async function abortUpload(project: string, sessionId: string): Promise<{ ok: true }> {
  const session = await sessionById(project, sessionId);
  if (!session || session.state !== "active") return { ok: true };
  if (session.upload_id) await abortMultipartUpload(session.type, project, session.file_id, getExtensionForMime(session.mime_type), session.upload_id).catch(() => {});
  const sql = getDb(); const ident = schemaIdent();
  await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='aborted' WHERE id=$1`, [session.id]);
  return { ok: true };
}

/** Abort the S3 multipart upload of each expired active session and mark it aborted. */
export async function cleanupExpiredUploadSessions(): Promise<void> {
  const sql = getDb(); const ident = schemaIdent();
  const sessions = await sql.unsafe<UploadSession[]>(`SELECT * FROM ${ident}.upload_sessions WHERE state='active' AND expires_at < now()`);
  for (const session of sessions) {
    if (session.upload_id) await abortMultipartUpload(session.type, session.project, session.file_id, getExtensionForMime(session.mime_type), session.upload_id).catch(() => {});
    await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='aborted' WHERE id=$1`, [session.id]);
  }
}
