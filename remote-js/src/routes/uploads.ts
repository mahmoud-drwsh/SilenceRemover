/** Shared presigned S3 upload sessions for pipeline media. */

import { Hono } from "hono";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { getDb, linkLegacyDerivedFilesForOriginal, schemaIdent } from "../db.ts";
import { probeDurationSeconds } from "../ffprobe.ts";
import { ALLOWED_MIME, AUDIO_MIME, VIDEO_MIME, getExtensionForMime, sniffMimeFromFile } from "../mime.ts";
import { HttpError, type FileType } from "../schemas.ts";
import { sanitizeFileId, sanitizeFilename } from "../sanitize.ts";
import {
  MULTIPART_PART_SIZE, abortMultipartUpload, completeMultipartUpload, presignPutObject,
  presignUploadPart, createMultipartUpload, storageGet,
} from "../storage.ts";
import { verifyMediaToken } from "../http.ts";
import { assertSourceOriginalExists, commitUploadMetadata, parseUploadTags, resolveUploadOverwrite } from "./files.ts";

export const uploadsRouter = new Hono();
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;
const MAX_PARTS = 10_000;
const COMPLETION_VERIFY_DELAYS_MS = [0, 500, 1_500, 3_000];

type UploadSession = {
  id: string; project: string; file_id: string; type: FileType; mime_type: string;
  file_size: number; checksum_sha256: string; title: string; tags: unknown;
  source_id: string | null; original_filename: string | null; upload_id: string | null;
  expires_at: string | Date; state: "active" | "completed" | "aborted";
};

function checksum(value: unknown): string {
  const result = String(value ?? "").toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(result)) throw new HttpError(400, "checksum_sha256 must be a SHA-256 hex digest");
  return result;
}

function parseBody(body: unknown): { id: string; type: FileType; mime: string; size: number; checksum: string; title: string; tags: string[]; sourceId: string | null; filename: string | null } {
  if (!body || typeof body !== "object") throw new HttpError(400, "JSON body is required");
  const data = body as Record<string, unknown>;
  const type = data.type;
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
  return { id, type, mime, size, checksum: checksum(data.checksum_sha256), title: String(data.title ?? ""), tags: parseUploadTags(tagValue, type), sourceId, filename };
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

async function sessionById(project: string, id: string): Promise<UploadSession | undefined> {
  const sql = getDb(); const ident = schemaIdent();
  return (await sql.unsafe<UploadSession[]>(`SELECT * FROM ${ident}.upload_sessions WHERE id = $1 AND project = $2`, [id, project]))[0];
}

uploadsRouter.post("/projects/:token/:project/api/uploads/initiate", async (c) => {
  const { token, project } = c.req.param(); await verifyMediaToken(token);
  const input = parseBody(await c.req.json().catch(() => null));
  await assertSourceOriginalExists(project, input.sourceId);
  const sql = getDb(); const ident = schemaIdent();
  const existing = (await sql.unsafe<UploadSession[]>(
    `SELECT * FROM ${ident}.upload_sessions WHERE project=$1 AND file_id=$2 AND type=$3 AND checksum_sha256=$4 AND state='active' AND expires_at > now() ORDER BY created_at DESC LIMIT 1`,
    [project, input.id, input.type, input.checksum],
  ))[0];
  const committed = (await sql.unsafe<{ checksum_sha256: string | null }[]>(
    `SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`, [project, input.id, input.type],
  ))[0];
  if (input.type === "original" && committed) {
    if (committed.checksum_sha256 === input.checksum) return c.json({ ok: true, id: input.id, type: input.type, already_uploaded: true });
    throw new HttpError(409, `Original '${input.id}' already exists with different bytes`);
  }
  const partCount = input.type === "audio" && input.size <= MULTIPART_PART_SIZE ? 0 : Math.ceil(input.size / MULTIPART_PART_SIZE);
  if (partCount > MAX_PARTS) throw new HttpError(413, "Upload exceeds multipart upload part limit");
  const overwritten = await resolveUploadOverwrite(input.id, project, input.type, input.title).catch((error) => {
    if (existing) return false;
    throw error;
  });
  if (existing) return c.json(await sessionResponse(existing, partCount, true));
  const ext = getExtensionForMime(input.mime);
  const uploadId = partCount ? await createMultipartUpload(input.type, project, input.id, ext, input.mime) : null;
  const session: UploadSession = {
    id: randomUUID(), project, file_id: input.id, type: input.type, mime_type: input.mime, file_size: input.size,
    checksum_sha256: input.checksum, title: input.title, tags: input.tags, source_id: input.sourceId,
    original_filename: input.filename, upload_id: uploadId, expires_at: new Date(Date.now() + SESSION_TTL_MS), state: "active",
  };
  await sql.unsafe(`INSERT INTO ${ident}.upload_sessions (id,project,file_id,type,mime_type,file_size,checksum_sha256,title,tags,source_id,original_filename,upload_id,expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11,$12,$13)`,
    [session.id, project, input.id, input.type, input.mime, input.size, input.checksum, input.title, JSON.stringify(input.tags), input.sourceId, input.filename, uploadId, session.expires_at]);
  return c.json({ ...(await sessionResponse(session, partCount, true)), overwritten });
});

async function sessionResponse(session: UploadSession, partCount: number, includeUrls: boolean): Promise<Record<string, unknown>> {
  const ext = getExtensionForMime(session.mime_type);
  if (!includeUrls) return { ok: true, session_id: session.id, id: session.file_id, type: session.type, resumed: true };
  if (!session.upload_id) return { ok: true, session_id: session.id, id: session.file_id, type: session.type, upload_url: await presignPutObject(session.type, session.project, session.file_id, ext, session.mime_type) };
  const urls = await Promise.all(Array.from({ length: partCount }, (_, index) => presignUploadPart(session.type, session.project, session.file_id, ext, session.upload_id!, index + 1)));
  return { ok: true, session_id: session.id, id: session.file_id, type: session.type, upload_id: session.upload_id, part_size: MULTIPART_PART_SIZE, urls };
}

uploadsRouter.post("/projects/:token/:project/api/uploads/:sessionId/complete", async (c) => {
  const { token, project, sessionId } = c.req.param(); await verifyMediaToken(token);
  const session = await sessionById(project, sessionId);
  if (!session) throw new HttpError(404, "Upload session not found");
  if (session.state === "completed") return c.json({ ok: true, id: session.file_id, type: session.type, already_completed: true });
  if (session.state !== "active" || new Date(session.expires_at).getTime() < Date.now()) throw new HttpError(409, "Upload session is no longer active");
  const ext = getExtensionForMime(session.mime_type);
  let overwritten = false;
  if (session.upload_id) {
    const parts = partsJson(await c.req.json().catch(() => null));
    if (!parts.length || parts.some((part) => !Number.isInteger(part.partNumber) || part.partNumber < 1 || !part.etag)) throw new HttpError(400, "Completed multipart ETags are required");
    await completeMultipartUpload(session.type, project, session.file_id, ext, session.upload_id, parts);
  }
  const tempDir = await mkdir(join(tmpdir(), `media-manager-${session.id}`), { recursive: true }).then(() => join(tmpdir(), `media-manager-${session.id}`));
  const tempPath = join(tempDir, `upload${ext}`);
  try {
    await downloadAndVerifyCompletedObject(session, ext, tempPath);
    const detected = await sniffMimeFromFile(tempPath);
    const allowedDetectedMime = session.type === "audio" ? AUDIO_MIME : VIDEO_MIME;
    if (!detected || !allowedDetectedMime.has(detected)) {
      throw new HttpError(400, `Uploaded object MIME type is invalid: expected ${session.type}, got ${detected ?? "unknown"}`);
    }
    const duration = await probeDurationSeconds(tempPath);
    overwritten = await resolveUploadOverwrite(session.file_id, project, session.type, session.title);
    await commitUploadMetadata({ fileId: session.file_id, project, fileType: session.type, title: session.type === "original" ? session.original_filename ?? session.file_id : session.title, tagList: sessionTags(session.tags), duration, fileSize: Number(session.file_size), mime: session.mime_type, overwritten, sourceId: session.source_id, originalFilename: session.original_filename, checksumSha256: session.checksum_sha256 });
    if (session.type === "original") {
      await linkLegacyDerivedFilesForOriginal(project, session.file_id);
    }
    const sql = getDb(); const ident = schemaIdent();
    await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='completed' WHERE id=$1`, [session.id]);
  } finally { await rm(tempDir, { recursive: true, force: true }); }
  return c.json({ ok: true, id: session.file_id, type: session.type, overwritten });
});

uploadsRouter.post("/projects/:token/:project/api/uploads/:sessionId/abort", async (c) => {
  const { token, project, sessionId } = c.req.param(); await verifyMediaToken(token);
  const session = await sessionById(project, sessionId);
  if (!session || session.state !== "active") return c.json({ ok: true });
  if (session.upload_id) await abortMultipartUpload(session.type, project, session.file_id, getExtensionForMime(session.mime_type), session.upload_id).catch(() => {});
  const sql = getDb(); const ident = schemaIdent(); await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='aborted' WHERE id=$1`, [session.id]);
  return c.json({ ok: true });
});

export async function cleanupExpiredUploadSessions(): Promise<void> {
  const sql = getDb(); const ident = schemaIdent();
  const sessions = await sql.unsafe<UploadSession[]>(`SELECT * FROM ${ident}.upload_sessions WHERE state='active' AND expires_at < now()`);
  for (const session of sessions) {
    if (session.upload_id) await abortMultipartUpload(session.type, session.project, session.file_id, getExtensionForMime(session.mime_type), session.upload_id).catch(() => {});
    await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='aborted' WHERE id=$1`, [session.id]);
  }
}
