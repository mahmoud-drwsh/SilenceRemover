import { Hono } from "hono";
import { getDb, schemaIdent } from "../db.ts";
import { verifyMediaToken } from "../http.ts";
import { ALLOWED_MIME, VIDEO_MIME, getExtensionForMime } from "../mime.ts";
import { HttpError } from "../schemas.ts";
import { sanitizeFileId, sanitizeFilename } from "../sanitize.ts";
import {
  abortOriginalMultipartUpload,
  completeOriginalMultipartUpload,
  createOriginalMultipartUpload,
  presignOriginalDownload,
  presignOriginalPart,
  storageHead,
  storageSha256,
} from "../storage.ts";

export const originalsRouter = new Hono();
const PART_SIZE = 8 * 1024 * 1024;
const MAX_PARTS = 10_000;

type UploadRow = {
  upload_id: string;
  file_id: string;
  mime_type: string;
  original_filename: string;
  checksum_sha256: string;
  file_size: number;
};

function requireChecksum(value: unknown): string {
  const checksum = String(value ?? "").toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(checksum)) throw new HttpError(400, "checksum_sha256 must be a SHA-256 hex digest");
  return checksum;
}

function parseInitiate(body: unknown): { filename: string; mime: string; size: number; checksum: string } {
  if (!body || typeof body !== "object") throw new HttpError(400, "JSON body is required");
  const data = body as Record<string, unknown>;
  const filename = sanitizeFilename(String(data.original_filename ?? ""));
  const mime = String(data.mime_type ?? "");
  const size = Number(data.file_size);
  if (!filename) throw new HttpError(400, "original_filename is required");
  if (!VIDEO_MIME.has(mime) || !ALLOWED_MIME.has(mime)) throw new HttpError(400, "Original must be a supported video MIME type");
  if (!Number.isSafeInteger(size) || size <= 0) throw new HttpError(400, "file_size must be a positive integer");
  return { filename, mime, size, checksum: requireChecksum(data.checksum_sha256) };
}

originalsRouter.post("/projects/:token/:project/api/originals/:id/upload", async (c) => {
  const { token, project, id: rawId } = c.req.param();
  await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId);
  if (!fileId) throw new HttpError(400, "Invalid original ID");
  const { filename, mime, size, checksum } = parseInitiate(await c.req.json().catch(() => null));
  const parts = Math.ceil(size / PART_SIZE);
  if (parts > MAX_PARTS) throw new HttpError(413, "Original exceeds multipart upload part limit");
  const sql = getDb();
  const ident = schemaIdent();
  const existing = await sql.unsafe<{ checksum_sha256: string }[]>(
    `SELECT checksum_sha256 FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = 'original'`, [fileId, project],
  );
  if (existing[0]) {
    if (existing[0].checksum_sha256 === checksum) return c.json({ ok: true, already_uploaded: true, id: fileId });
    throw new HttpError(409, `Original '${fileId}' already exists with different bytes`);
  }
  const ext = getExtensionForMime(mime);
  const uploadId = await createOriginalMultipartUpload(project, fileId, ext, mime);
  await sql.unsafe(
    `INSERT INTO ${ident}.original_uploads (upload_id, project, file_id, mime_type, original_filename, checksum_sha256, file_size) VALUES ($1, $2, $3, $4, $5, $6, $7)`,
    [uploadId, project, fileId, mime, filename, checksum, size],
  );
  const urls = await Promise.all(Array.from({ length: parts }, (_, index) => presignOriginalPart(project, fileId, ext, uploadId, index + 1)));
  return c.json({ ok: true, id: fileId, upload_id: uploadId, part_size: PART_SIZE, urls });
});

originalsRouter.post("/projects/:token/:project/api/originals/:id/complete", async (c) => {
  const { token, project, id: rawId } = c.req.param();
  await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId);
  if (!fileId) throw new HttpError(400, "Invalid original ID");
  const body = await c.req.json().catch(() => null) as { upload_id?: unknown; parts?: unknown } | null;
  const uploadId = String(body?.upload_id ?? "");
  const parts = Array.isArray(body?.parts) ? body!.parts.map((part) => ({ partNumber: Number((part as Record<string, unknown>).part_number), etag: String((part as Record<string, unknown>).etag ?? "") })) : [];
  if (!uploadId || parts.length === 0 || parts.some((part) => !Number.isInteger(part.partNumber) || part.partNumber < 1 || !part.etag)) throw new HttpError(400, "upload_id and completed parts are required");
  const sql = getDb();
  const ident = schemaIdent();
  const uploads = await sql.unsafe<UploadRow[]>(`SELECT upload_id, file_id, mime_type, original_filename, checksum_sha256, file_size FROM ${ident}.original_uploads WHERE upload_id = $1 AND project = $2`, [uploadId, project]);
  const upload = uploads[0];
  if (!upload || upload.file_id !== fileId) throw new HttpError(404, "Upload session not found");
  const ext = getExtensionForMime(upload.mime_type);
  try {
    await completeOriginalMultipartUpload(project, fileId, ext, uploadId, parts);
    const head = await storageHead("original", project, fileId, ext);
    if (!head || head.size !== Number(upload.file_size)) throw new HttpError(400, "Uploaded object size does not match request");
    const checksum = await storageSha256("original", project, fileId, ext);
    if (checksum !== upload.checksum_sha256) throw new HttpError(400, "Uploaded object checksum does not match request");
    await sql.begin(async (tx) => {
      await tx.unsafe(`INSERT INTO ${ident}.files (id, project, type, title, tags, duration, file_size, mime_type, original_filename, checksum_sha256) VALUES ($1, $2, 'original', $3, '[]'::jsonb, 0, $4, $5, $6, $7)`, [fileId, project, upload.original_filename, upload.file_size, upload.mime_type, upload.original_filename, upload.checksum_sha256]);
      await tx.unsafe(`DELETE FROM ${ident}.original_uploads WHERE upload_id = $1`, [uploadId]);
    });
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw error;
  }
  return c.json({ ok: true, id: fileId, type: "original" });
});

originalsRouter.post("/projects/:token/:project/api/originals/:id/abort", async (c) => {
  const { token, project, id: rawId } = c.req.param();
  await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId);
  const body = await c.req.json().catch(() => null) as { upload_id?: unknown } | null;
  if (!fileId || !body?.upload_id) throw new HttpError(400, "original ID and upload_id are required");
  const sql = getDb(); const ident = schemaIdent(); const uploadId = String(body.upload_id);
  const uploads = await sql.unsafe<UploadRow[]>(`SELECT upload_id, file_id, mime_type, original_filename, checksum_sha256, file_size FROM ${ident}.original_uploads WHERE upload_id = $1 AND project = $2`, [uploadId, project]);
  const upload = uploads[0];
  if (!upload || upload.file_id !== fileId) throw new HttpError(404, "Upload session not found");
  await abortOriginalMultipartUpload(project, fileId, getExtensionForMime(upload.mime_type), uploadId);
  await sql.unsafe(`DELETE FROM ${ident}.original_uploads WHERE upload_id = $1`, [uploadId]);
  return c.json({ ok: true });
});

originalsRouter.get("/projects/:token/:project/api/originals/:id/download", async (c) => {
  const { token, project, id: rawId } = c.req.param();
  await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId);
  if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ mime_type: string; original_filename: string | null; tags: unknown }[]>(`SELECT mime_type, original_filename, tags FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = 'original'`, [fileId, project]);
  const row = rows[0];
  if (!row || (Array.isArray(row.tags) && row.tags.includes("trash"))) throw new HttpError(404, "Original not found");
  const filename = sanitizeFilename(row.original_filename ?? fileId) || fileId;
  const url = await presignOriginalDownload(project, fileId, getExtensionForMime(row.mime_type), filename);
  return c.json({ url, expires_in_sec: 300, filename });
});

originalsRouter.get("/projects/:token/:project/api/originals/:id/derived", async (c) => {
  const { token, project, id: rawId } = c.req.param(); await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId); if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe(`SELECT id, project, type, title, tags, duration, file_size, mime_type, source_id, created_at FROM ${ident}.files WHERE project = $1 AND source_id = $2 ORDER BY type, id`, [project, fileId]);
  return c.json(rows);
});
