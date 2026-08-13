/**
 * GET / POST / PUT / DELETE /projects/:token/:project/api/files
 *
 * 1:1 port of the four file endpoints in remote/app.py - same query
 * parameters, same response shapes, same status codes, same SQL predicates
 * (including the `tags::text LIKE '%"<tag>"%'` shape we inherit from the
 * Python service).
 */

import { Hono } from "hono";
import { getDb, schemaIdent } from "../db.ts";
import { verifyMediaToken } from "../http.ts";
import {
  ALLOWED_MIME,
  VIDEO_MIME,
  getExtensionForMime,
  sniffMimeFromBytes,
  sniffMimeFromFile,
} from "../mime.ts";
import { loadConfig } from "../config.ts";
import {
  HttpError,
  type FileResponse,
  type FileType,
  validateAudioTags,
} from "../schemas.ts";
import { normalizeTitle, sanitizeFileId } from "../sanitize.ts";
import {
  storageDelete,
  storageDeleteAnyExtension,
  presignProjectOverlayLogoPut,
  storageProjectOverlayLogoSha256,
  storagePutProjectOverlayLogo,
  storagePutBytes,
} from "../storage.ts";
import { probeDurationSeconds } from "../ffprobe.ts";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { createHash } from "node:crypto";

export const filesRouter = new Hono();

const MAX_OVERLAY_LOGO_BYTES = 10 * 1024 * 1024;
const PNG_SIGNATURE = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);

/**
 * Client migration seam: a project media token may seed its logo once, but
 * cannot replace an existing admin-managed logo.
 */
filesRouter.put("/projects/:token/:project/api/overlay-logo-if-missing", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);
  const contentType = c.req.header("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  const declaredLength = Number(c.req.header("content-length"));
  if (contentType !== "image/png") throw new HttpError(415, "Overlay logo must be an image/png file");
  if (!Number.isSafeInteger(declaredLength) || declaredLength <= 0 || declaredLength > MAX_OVERLAY_LOGO_BYTES) {
    throw new HttpError(413, "Overlay logo must be no larger than 10 MiB");
  }
  const sql = getDb(); const ident = schemaIdent();
  const existing = (await sql.unsafe<{ project: string }[]>(
    `SELECT project FROM ${ident}.project_overlay_logos WHERE project=$1`, [project],
  ))[0];
  if (existing) return c.json({ ok: true, uploaded: false, reason: "already_configured" });
  const bytes = new Uint8Array(await c.req.arrayBuffer());
  if (bytes.byteLength !== declaredLength || bytes.byteLength < PNG_SIGNATURE.byteLength || !PNG_SIGNATURE.every((value, index) => bytes[index] === value)) {
    throw new HttpError(415, "Overlay logo content is not a PNG file");
  }
  const projectExists = (await sql.unsafe<{ project: string }[]>(
    `SELECT project FROM ${ident}.files WHERE project=$1 LIMIT 1`, [project],
  ))[0];
  if (!projectExists) throw new HttpError(404, "Project not found");
  const checksum = createHash("sha256").update(bytes).digest("hex");
  await storagePutProjectOverlayLogo(project, bytes);
  const inserted = await sql.unsafe<{ project: string }[]>(`
    INSERT INTO ${ident}.project_overlay_logos (project, checksum_sha256, file_size, updated_at)
    VALUES ($1,$2,$3,now())
    ON CONFLICT (project) DO NOTHING
    RETURNING project`, [project, checksum, bytes.byteLength]);
  if (!inserted[0]) return c.json({ ok: true, uploaded: false, reason: "already_configured" });
  return c.json({ ok: true, uploaded: true, checksum_sha256: checksum, file_size: bytes.byteLength }, 201);
});

function parseLogoSeedPayload(body: unknown): { size: number; checksum: string } {
  const value = body as { size?: unknown; checksum_sha256?: unknown } | null;
  const size = Number(value?.size);
  const checksum = String(value?.checksum_sha256 ?? "").toLowerCase();
  if (!Number.isSafeInteger(size) || size <= 0 || size > MAX_OVERLAY_LOGO_BYTES || !/^[a-f0-9]{64}$/.test(checksum)) {
    throw new HttpError(400, "Valid PNG size and checksum_sha256 are required");
  }
  return { size, checksum };
}

/** JSON/R2 migration path for clients whose proxy resets binary requests. */
filesRouter.post("/projects/:token/:project/api/overlay-logo-if-missing/initiate", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);
  const { size, checksum } = parseLogoSeedPayload(await c.req.json().catch(() => null));
  const sql = getDb(); const ident = schemaIdent();
  const existing = (await sql.unsafe<{ project: string }[]>(`SELECT project FROM ${ident}.project_overlay_logos WHERE project=$1`, [project]))[0];
  if (existing) return c.json({ ok: true, already_configured: true });
  const projectExists = (await sql.unsafe<{ project: string }[]>(`SELECT project FROM ${ident}.files WHERE project=$1 LIMIT 1`, [project]))[0];
  if (!projectExists) throw new HttpError(404, "Project not found");
  return c.json({ ok: true, already_configured: false, size, checksum_sha256: checksum, upload_url: await presignProjectOverlayLogoPut(project) });
});

filesRouter.post("/projects/:token/:project/api/overlay-logo-if-missing/complete", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);
  const { size, checksum } = parseLogoSeedPayload(await c.req.json().catch(() => null));
  const sql = getDb(); const ident = schemaIdent();
  const existing = (await sql.unsafe<{ project: string }[]>(`SELECT project FROM ${ident}.project_overlay_logos WHERE project=$1`, [project]))[0];
  if (existing) return c.json({ ok: true, uploaded: false, reason: "already_configured" });
  const stored = await storageProjectOverlayLogoSha256(project);
  if (!stored || stored.size !== size || stored.checksum !== checksum) {
    throw new HttpError(400, "Uploaded overlay logo verification failed");
  }
  const inserted = await sql.unsafe<{ project: string }[]>(`
    INSERT INTO ${ident}.project_overlay_logos (project, checksum_sha256, file_size, updated_at)
    VALUES ($1,$2,$3,now()) ON CONFLICT (project) DO NOTHING RETURNING project`, [project, checksum, size]);
  return c.json({ ok: true, uploaded: Boolean(inserted[0]), reason: inserted[0] ? undefined : "already_configured" });
});

interface FileRow {
  id: string;
  project: string;
  type: FileType;
  title: string | null;
  tags: unknown;
  duration: number | null;
  file_size: number | null;
  mime_type: string;
  created_at: Date | string | null;
  source_id: string | null;
  original_filename: string | null;
  checksum_sha256: string | null;
  derived_title: string | null;
  no_overlay_id: string | null;
  designer_video_id: string | null;
  subtitle_id: string | null;
  designer_of_id: string | null;
}

function rowToResponse(row: FileRow): FileResponse {
  return {
    id: row.id,
    project: row.project,
    type: row.type,
    title: row.title ?? null,
    tags: parseTagsValue(row.tags),
    duration: Number(row.duration ?? 0),
    file_size: Number(row.file_size ?? 0),
    mime_type: row.mime_type,
    created_at: serializeCreatedAt(row.created_at),
    source_id: row.source_id ?? null,
    original_filename: row.original_filename ?? null,
    checksum_sha256: row.checksum_sha256 ?? null,
    derived_title: row.derived_title ?? null,
    no_overlay_id: row.no_overlay_id ?? null,
    designer_video_id: row.designer_video_id ?? null,
    subtitle_id: row.subtitle_id ?? null,
    designer_of_id: row.designer_of_id ?? null,
  };
}

function serializeCreatedAt(value: Date | string | null): string {
  if (!value) return "";
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

export function parseTagsValue(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed.map(String);
    } catch {
      return [];
    }
  }
  return [];
}

function parseTagsParam(value: string | undefined): string[] | null {
  if (!value) return null;
  const split = value
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  return split.length > 0 ? split : null;
}

export function parseUploadTags(value: string, fileType: FileType): string[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) throw new Error("Tags must be an array");
  } catch (err) {
    throw new HttpError(
      400,
      `Invalid tags format: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  let tags = parsed.map(String);
  if (fileType === "audio") {
    tags = validateAudioTags(tags);
  }

  if (tags.length === 0 && fileType === "audio") {
    tags = ["todo"];
  }
  return tags;
}

export async function assertSourceOriginalExists(project: string, sourceId: string | null): Promise<void> {
  if (!sourceId) return;
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ tags: unknown }[]>(
    `SELECT tags FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = 'original'`,
    [sourceId, project],
  );
  if (!rows[0] || parseTagsValue(rows[0].tags).includes("trash")) {
    throw new HttpError(400, "source_id must reference an available original in this project");
  }
}

export async function resolveUploadOverwrite(
  fileId: string,
  project: string,
  fileType: FileType,
  title: string,
): Promise<boolean> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{
    id: string;
    title: string | null;
    mime_type: string;
  }[]>(
    `SELECT id, title, mime_type, file_size, duration
       FROM ${ident}.files
       WHERE id = $1 AND project = $2 AND type = $3`,
    [fileId, project, fileType],
  );
  const existing = rows[0];
  if (!existing) return false;

  if (fileType === "audio") {
    throw new HttpError(409, `Audio file with id '${fileId}' already exists`);
  }
  if (fileType === "subtitle") {
    return true;
  }

  const oldTitle = normalizeTitle(existing.title);
  const newTitle = normalizeTitle(title);
  if (oldTitle === newTitle) {
    throw new HttpError(409, "Video with same title already exists");
  }

  console.log(
    `[OVERWRITE] Video '${fileId}': title changed from '${oldTitle}' to '${newTitle}'`,
  );
  return true;
}

export async function commitUploadMetadata(args: {
  fileId: string;
  project: string;
  fileType: FileType;
  title: string;
  tagList: string[];
  duration: number;
  fileSize: number;
  mime: string;
  overwritten: boolean;
  sourceId?: string | null;
  originalFilename?: string | null;
  checksumSha256?: string | null;
  designerOfId?: string | null;
}): Promise<void> {
  const sql = getDb();
  const ident = schemaIdent();
  if (args.overwritten) {
    await sql.unsafe(
      `DELETE FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
      [args.fileId, args.project, args.fileType],
    );
  }

  try {
    await sql.unsafe(
      `INSERT INTO ${ident}.files
         (id, project, type, title, tags, duration, file_size, mime_type, source_id, original_filename, checksum_sha256, designer_of_id)
       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12)`,
      [
        args.fileId,
        args.project,
        args.fileType,
        args.title,
        JSON.stringify(args.tagList),
        args.duration,
        args.fileSize,
        args.mime,
        args.sourceId ?? null,
        args.originalFilename ?? null,
        args.checksumSha256 ?? null,
        args.designerOfId ?? null,
      ],
    );
  } catch (error) {
    throw mapUploadMetadataInsertError(error, args.fileId);
  }
}

export function mapUploadMetadataInsertError(error: unknown, fileId: string): unknown {
  if (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "23505"
  ) {
    return new HttpError(409, `File with id '${fileId}' already exists`);
  }
  return error;
}

function elapsedSeconds(startedAt: number): string {
  return ((performance.now() - startedAt) / 1000).toFixed(1);
}

export function parseContentLengthHeader(value: string | undefined): number {
  if (value === undefined) {
    throw new HttpError(411, "Content-Length is required");
  }
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) {
    throw new HttpError(400, "Invalid Content-Length");
  }
  return Number.parseInt(trimmed, 10);
}

export function addTagListConditions(args: {
  conditions: string[];
  params: (string | number | boolean | null | string[])[];
  tagList: string[] | null;
  includeTrash: boolean;
  includePending: boolean;
  excludedTags?: string[];
}): void {
  const normalizedTagsSql =
    "CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END";

  if (args.tagList) {
    for (const tag of args.tagList) {
      args.params.push([tag]);
      args.conditions.push(`${normalizedTagsSql} @> CAST($${args.params.length} AS jsonb)`);
    }
  } else if (!args.includeTrash) {
    args.params.push(["trash"]);
    args.conditions.push(`NOT (${normalizedTagsSql} @> CAST($${args.params.length} AS jsonb))`);
  }

  for (const tag of args.excludedTags ?? []) {
    args.params.push([tag]);
    args.conditions.push(`NOT (${normalizedTagsSql} @> CAST($${args.params.length} AS jsonb))`);
  }
}

/* -------------------------------------------------------------------------- */
/* GET /api/files                                                             */
/* -------------------------------------------------------------------------- */

filesRouter.get("/projects/:token/:project/api/files", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);

  const url = new URL(c.req.url);
  const typeParam = url.searchParams.get("type") as FileType | null;
  const tagsParam = url.searchParams.get("tags") ?? undefined;
  const sort = url.searchParams.get("sort") ?? "asc";
  const checkId = url.searchParams.get("check_id");
  const checkTitle = url.searchParams.get("check_title");
  const includeTrash = url.searchParams.get("include_trash") === "true";
  const includePending = url.searchParams.get("include_pending") === "true";
  const designerMissing = url.searchParams.get("designer_missing") === "true";

  if (typeParam && typeParam !== "audio" && typeParam !== "video" && typeParam !== "original" && typeParam !== "subtitle") {
    throw new HttpError(400, "Invalid type parameter");
  }

  const sql = getDb();
  const ident = schemaIdent();

  // Pre-flight check mode: check_id provided
  if (checkId !== null) {
    const sanitizedId = sanitizeFileId(checkId);
    if (!sanitizedId) {
      throw new HttpError(400, "Invalid check_id");
    }
    if (!typeParam) {
      throw new HttpError(400, "Type parameter is required when using check_id");
    }

    const rows = await sql.unsafe<FileRow[]>(
      `SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at, source_id, original_filename, checksum_sha256, NULL::text AS derived_title, NULL::text AS no_overlay_id, NULL::text AS designer_video_id, NULL::text AS subtitle_id, designer_of_id
       FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
      [sanitizedId, project, typeParam],
    );
    const row = rows[0];

    if (row) {
      const existingTitle = normalizeTitle(row.title);
      const response = rowToResponse(row);
      if (checkTitle !== null) {
        const checkTitleNormalized = normalizeTitle(checkTitle);
        const wouldOverwrite = existingTitle !== checkTitleNormalized;
        return c.json([
          {
            ...response,
            exists: true,
            would_overwrite: wouldOverwrite,
            existing_title: existingTitle,
            provided_title: checkTitleNormalized,
          },
        ]);
      }
      return c.json([response]);
    }

    return c.json([
      {
        exists: false,
        id: sanitizedId,
        type: typeParam,
        project,
      },
    ]);
  }

  // Normal list mode
  const tagList = parseTagsParam(tagsParam);

  const conditions: string[] = ["project = $1"];
  const params: (string | number | boolean | null | string[])[] = [project];

  if (typeParam) {
    params.push(typeParam);
    conditions.push(`type = $${params.length}`);
  }

  if (designerMissing) {
    if (typeParam !== "video") throw new HttpError(400, "designer_missing requires type=video");
    conditions.push(`NOT EXISTS (
      SELECT 1 FROM ${ident}.files AS designer_candidate
      WHERE designer_candidate.project = source.project
        AND designer_candidate.type = 'video'
        AND designer_candidate.designer_of_id = source.id
        AND NOT ((CASE WHEN jsonb_typeof(designer_candidate.tags) = 'string' THEN (designer_candidate.tags #>> '{}')::jsonb ELSE designer_candidate.tags END) @> '["trash"]'::jsonb)
    )`);
  }

  addTagListConditions({
    conditions,
    params,
    tagList,
    includeTrash,
    includePending,
    excludedTags:
      typeParam === "video" &&
      !tagList?.some((tag) => tag === "no-overlay" || tag === "designer" || tag === "trash")
        ? ["no-overlay", "designer"]
        : [],
  });

  const whereClause = conditions.join(" AND ");
  const sortDirection = sort === "asc" ? "ASC" : "DESC";

  const rows = await sql.unsafe<FileRow[]>(
    `SELECT source.id, source.project, source.type, source.title, source.tags, source.duration, source.file_size, source.mime_type, source.created_at, source.source_id, source.original_filename, source.checksum_sha256, derived.title AS derived_title, companion.id AS no_overlay_id, designer.id AS designer_video_id, subtitle.id AS subtitle_id, source.designer_of_id
     FROM ${ident}.files AS source
     LEFT JOIN LATERAL (
       SELECT title
       FROM ${ident}.files AS candidate
       WHERE candidate.project = source.project
         AND candidate.source_id = source.id
         AND candidate.type IN ('video', 'audio')
         AND COALESCE(BTRIM(candidate.title), '') <> ''
         AND NOT ((CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb)
       ORDER BY CASE candidate.type WHEN 'video' THEN 0 ELSE 1 END,
         CASE WHEN (CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["no-overlay"]'::jsonb THEN 1 ELSE 0 END
       LIMIT 1
     ) AS derived ON TRUE
     LEFT JOIN LATERAL (
       SELECT candidate.id
       FROM ${ident}.files AS candidate
       WHERE source.type = 'video'
         AND source.source_id IS NOT NULL
         AND NOT ((CASE WHEN jsonb_typeof(source.tags) = 'string' THEN (source.tags #>> '{}')::jsonb ELSE source.tags END) @> '["no-overlay"]'::jsonb)
         AND candidate.project = source.project
         AND candidate.type = 'video'
         AND candidate.source_id = source.source_id
         AND candidate.id <> source.id
         AND (CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["no-overlay"]'::jsonb
         AND NOT ((CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb)
       ORDER BY candidate.created_at DESC, candidate.id
       LIMIT 1
     ) AS companion ON TRUE
     LEFT JOIN LATERAL (
       SELECT candidate.id
       FROM ${ident}.files AS candidate
       WHERE source.type = 'video'
         AND candidate.project = source.project
         AND candidate.type = 'video'
         AND candidate.designer_of_id = source.id
         AND NOT ((CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb)
       ORDER BY candidate.created_at DESC, candidate.id
       LIMIT 1
     ) AS designer ON TRUE
     LEFT JOIN LATERAL (
       SELECT candidate.id
       FROM ${ident}.files AS candidate
       WHERE source.type = 'video'
         AND source.source_id IS NOT NULL
         AND candidate.project = source.project
         AND candidate.type = 'subtitle'
         AND candidate.id = source.source_id || '-subtitles'
       LIMIT 1
     ) AS subtitle ON TRUE
     WHERE ${whereClause}
     ORDER BY source.id ${sortDirection}`,
    params,
  );

  return c.json(rows.map(rowToResponse));
});

/* -------------------------------------------------------------------------- */
/* POST /api/audio/approve-pending                                            */
/* -------------------------------------------------------------------------- */

filesRouter.post("/projects/:token/:project/api/audio/approve-pending", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);
  const body = await c.req.json().catch(() => null) as { confirm?: unknown } | null;
  if (body?.confirm !== true) throw new HttpError(400, "Explicit confirmation is required");

  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.files
    SET tags = '["ready"]'::jsonb
    WHERE project = $1
      AND type = 'audio'
      AND (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END) @> '["todo"]'::jsonb
      AND NOT ((CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END) @> '["trash"]'::jsonb)
    RETURNING id
  `, [project]);
  return c.json({ ok: true, approved_count: rows.length });
});

/* -------------------------------------------------------------------------- */
/* POST /api/files                                                            */
/* -------------------------------------------------------------------------- */

filesRouter.post("/_removed/projects/:token/:project/api/files", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);

  const config = loadConfig();
  const formData = await c.req.raw.formData();

  const idRaw = formData.get("id");
  const titleRaw = formData.get("title") ?? "";
  const typeRaw = formData.get("type");
  const tagsRaw = formData.get("tags") ?? "[]";
  const sourceIdRaw = formData.get("source_id");
  const file = formData.get("file");

  if (typeof idRaw !== "string" || typeof typeRaw !== "string") {
    throw new HttpError(400, "Missing required form fields");
  }
  if (!(file instanceof File)) {
    throw new HttpError(400, "Missing file upload");
  }
  if (typeRaw !== "audio" && typeRaw !== "video") {
    throw new HttpError(400, "Invalid type parameter");
  }
  const fileType = typeRaw as FileType;
  const title = typeof titleRaw === "string" ? titleRaw : "";

  const id = sanitizeFileId(idRaw);
  if (!id) {
    throw new HttpError(400, "Invalid file ID");
  }
  const sourceId = typeof sourceIdRaw === "string" && sourceIdRaw ? sanitizeFileId(sourceIdRaw) : null;
  if (sourceIdRaw && !sourceId) throw new HttpError(400, "Invalid source_id");
  await assertSourceOriginalExists(project, sourceId);

  const overwritten = await resolveUploadOverwrite(id, project, fileType, title);
  const tagList = parseUploadTags(
    typeof tagsRaw === "string" ? tagsRaw : "[]",
    fileType,
  );

  // Read upload body
  const contentBytes = new Uint8Array(await file.arrayBuffer());
  if (contentBytes.byteLength > config.maxFileSizeBytes) {
    throw new HttpError(
      413,
      `File too large (max ${config.maxFileSizeBytes} bytes)`,
    );
  }

  // Sniff MIME from the raw bytes (libmagic-equivalent).
  const mime = await sniffMimeFromBytes(contentBytes);
  if (!mime || !ALLOWED_MIME.has(mime)) {
    throw new HttpError(400, `Invalid file type: ${mime ?? "unknown"}`);
  }

  const ext = getExtensionForMime(mime);

  // Probe duration via ffprobe against a temp file.
  let duration = 0;
  const tempDir = join(
    tmpdir(),
    `media-manager-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  );
  await mkdir(tempDir, { recursive: true });
  const tempPath = join(tempDir, `upload${ext}`);
  try {
    await writeFile(tempPath, contentBytes);
    duration = await probeDurationSeconds(tempPath);
    await storagePutBytes(fileType, project, id, ext, contentBytes, mime);
  } finally {
    await rm(tempDir, { recursive: true, force: true }).catch(() => {});
  }

  await commitUploadMetadata({
    fileId: id,
    project,
    fileType,
    title,
    tagList,
    duration,
    fileSize: contentBytes.byteLength,
    mime,
    overwritten,
    sourceId,
  });

  return c.json({
    ok: true,
    id,
    type: fileType,
    overwritten,
  });
});

/* -------------------------------------------------------------------------- */
/* PUT /api/files/:id/content                                                 */
/* -------------------------------------------------------------------------- */

filesRouter.put("/_removed/projects/:token/:project/api/files/:id/content", async (c) => {
  const { token, project, id: idRaw } = c.req.param();
  await verifyMediaToken(token);

  const config = loadConfig();
  const fileType: FileType = "video";
  const fileId = sanitizeFileId(idRaw);
  if (!fileId) {
    throw new HttpError(400, "Invalid file ID");
  }

  const url = new URL(c.req.url);
  const title = url.searchParams.get("title") ?? "";
  const sourceIdRaw = url.searchParams.get("source_id");
  const sourceId = sourceIdRaw ? sanitizeFileId(sourceIdRaw) : null;
  if (sourceIdRaw && !sourceId) throw new HttpError(400, "Invalid source_id");
  await assertSourceOriginalExists(project, sourceId);
  const tagList = parseUploadTags(url.searchParams.get("tags") ?? "[]", fileType);
  const overwritten = await resolveUploadOverwrite(fileId, project, fileType, title);

  const expectedSize = parseContentLengthHeader(c.req.header("content-length"));
  if (expectedSize > config.maxFileSizeBytes) {
    throw new HttpError(413, `File too large (max ${config.maxFileSizeBytes} bytes)`);
  }

  const uploadStartedAt = performance.now();
  console.log(
    `UPLOAD_START id=${JSON.stringify(fileId)} project=${JSON.stringify(project)} ` +
      `type=${JSON.stringify(fileType)} raw_body=True expected_bytes=${expectedSize} ` +
      `tags=${JSON.stringify(tagList)}`,
  );

  let bytesReceived = 0;
  let tempDir: string | null = null;
  try {
    const body = c.req.raw.body;
    if (!body) {
      throw new HttpError(400, "Missing request body");
    }

    tempDir = join(
      tmpdir(),
      `media-manager-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    );
    await mkdir(tempDir, { recursive: true });
    const tempPath = join(tempDir, "upload");
    const writer = createWriteStream(tempPath, { flags: "wx" });

    try {
      for await (const chunk of body) {
        if (chunk.byteLength === 0) continue;
        bytesReceived += chunk.byteLength;
        if (bytesReceived > config.maxFileSizeBytes) {
          throw new HttpError(413, `File too large (max ${config.maxFileSizeBytes} bytes)`);
        }
        if (!writer.write(Buffer.from(chunk))) {
          await once(writer, "drain");
        }
      }
      writer.end();
      await once(writer, "finish");
    } catch (err) {
      writer.destroy();
      throw err;
    }

    console.log(
      `UPLOAD_RECEIVED id=${JSON.stringify(fileId)} project=${JSON.stringify(project)} ` +
        `type=${JSON.stringify(fileType)} bytes=${bytesReceived} ` +
        `elapsed_sec=${elapsedSeconds(uploadStartedAt)}`,
    );

    if (bytesReceived !== expectedSize) {
      throw new HttpError(
        400,
        `Incomplete upload: expected ${expectedSize} bytes, got ${bytesReceived}`,
      );
    }

    const mime = await sniffMimeFromFile(tempPath);
    if (!mime || !VIDEO_MIME.has(mime)) {
      throw new HttpError(400, `Invalid video file type: ${mime ?? "unknown"}`);
    }

    const ext = getExtensionForMime(mime);
    const duration = await probeDurationSeconds(tempPath);
    const contentBytes = await readFile(tempPath);
    await storagePutBytes(fileType, project, fileId, ext, contentBytes, mime);
    console.log(
      `UPLOAD_STORED id=${JSON.stringify(fileId)} project=${JSON.stringify(project)} ` +
        `type=${JSON.stringify(fileType)} bytes=${bytesReceived} ` +
        `elapsed_sec=${elapsedSeconds(uploadStartedAt)}`,
    );

    await commitUploadMetadata({
      fileId,
      project,
      fileType,
      title,
      tagList,
      duration,
      fileSize: bytesReceived,
      mime,
      overwritten,
      sourceId,
    });
    console.log(
      `UPLOAD_COMMITTED id=${JSON.stringify(fileId)} project=${JSON.stringify(project)} ` +
        `type=${JSON.stringify(fileType)} bytes=${bytesReceived} overwritten=${overwritten} ` +
        `elapsed_sec=${elapsedSeconds(uploadStartedAt)}`,
    );

    return c.json({
      ok: true,
      id: fileId,
      type: fileType,
      overwritten,
    });
  } catch (err) {
    console.log(
      `UPLOAD_FAILED id=${JSON.stringify(fileId)} project=${JSON.stringify(project)} ` +
        `type=${JSON.stringify(fileType)} bytes=${bytesReceived} ` +
        `error_type=${err instanceof Error ? err.constructor.name : typeof err} ` +
        `error=${JSON.stringify(err instanceof Error ? err.message : String(err))} ` +
        `elapsed_sec=${elapsedSeconds(uploadStartedAt)}`,
    );
    throw err;
  } finally {
    if (tempDir) {
      await rm(tempDir, { recursive: true, force: true }).catch(() => {});
    }
  }
});

/* -------------------------------------------------------------------------- */
/* PUT /api/files/:id                                                         */
/* -------------------------------------------------------------------------- */

filesRouter.put("/projects/:token/:project/api/files/:id", async (c) => {
  const { token, project, id: idRaw } = c.req.param();
  await verifyMediaToken(token);

  const url = new URL(c.req.url);
  const typeRaw = url.searchParams.get("type");
  if (typeRaw !== "audio" && typeRaw !== "video" && typeRaw !== "original" && typeRaw !== "subtitle") {
    throw new HttpError(400, "Type parameter is required");
  }
  const fileType = typeRaw as FileType;

  const id = sanitizeFileId(idRaw);
  if (!id) {
    throw new HttpError(400, "Invalid file ID");
  }

  const body = await c.req.json().catch(() => null);
  if (!body || !Array.isArray(body.tags)) {
    throw new HttpError(400, "Body must include tags array");
  }
  let tags = body.tags.map(String);
  const title: string | null | undefined =
    body.title === undefined
      ? undefined
      : body.title === null
        ? null
        : String(body.title);

  const sql = getDb();
  const ident = schemaIdent();

  const rows = await sql.unsafe<{ type: FileType }[]>(
    `SELECT type FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
    [id, project, fileType],
  );
  if (rows.length === 0) {
    throw new HttpError(404, `File '${id}' of type '${fileType}' not found`);
  }
  const rowType = rows[0]!.type;

  if (rowType === "audio") {
    tags = validateAudioTags(tags);
  }
  if (tags.length === 0 && rowType === "audio") {
    tags = ["todo"];
  }

  if (title !== undefined) {
    await sql.unsafe(
      `UPDATE ${ident}.files
         SET tags = $1::jsonb, title = $2
         WHERE id = $3 AND project = $4 AND type = $5`,
      [JSON.stringify(tags), title, id, project, rowType],
    );
  } else {
    await sql.unsafe(
      `UPDATE ${ident}.files
         SET tags = $1::jsonb
         WHERE id = $2 AND project = $3 AND type = $4`,
      [JSON.stringify(tags), id, project, rowType],
    );
  }

  return c.json({
    ok: true,
    id,
    tags,
    title: title ?? null,
  });
});

/* -------------------------------------------------------------------------- */
/* DELETE /api/files/:id                                                      */
/* -------------------------------------------------------------------------- */

filesRouter.delete("/projects/:token/:project/api/files/:id", async (c) => {
  const { token, project, id: idRaw } = c.req.param();
  await verifyMediaToken(token);

  const url = new URL(c.req.url);
  const typeRaw = url.searchParams.get("type");
  if (typeRaw !== "audio" && typeRaw !== "video" && typeRaw !== "original" && typeRaw !== "subtitle") {
    throw new HttpError(400, "Type parameter is required");
  }
  const fileType = typeRaw as FileType;

  const id = sanitizeFileId(idRaw);
  if (!id) {
    throw new HttpError(400, "Invalid file ID");
  }

  const sql = getDb();
  const ident = schemaIdent();

  const rows = await sql.unsafe<{
    type: FileType;
    tags: unknown;
    mime_type: string;
  }[]>(
    `SELECT type, tags, mime_type
       FROM ${ident}.files
       WHERE id = $1 AND project = $2 AND type = $3`,
    [id, project, fileType],
  );
  if (rows.length === 0) {
    throw new HttpError(404, `File '${id}' of type '${fileType}' not found`);
  }
  const row = rows[0]!;
  const tags = parseTagsValue(row.tags);
  if (!tags.includes("trash")) {
    throw new HttpError(
      400,
      "Only trashed files can be deleted. Add 'trash' tag first.",
    );
  }

  const ext = getExtensionForMime(row.mime_type);
  try {
    await storageDelete(row.type, project, id, ext);
  } catch {
    await storageDeleteAnyExtension(row.type, project, id);
  }

  await sql.unsafe(
    `DELETE FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
    [id, project, row.type],
  );

  return c.json({ ok: true, id, deleted: true });
});
