/**
 * GET /projects/:token/:project/stream/:id
 *
 * Range-aware S3 streaming. Mirrors `stream_file` in remote/app.py: looks up
 * metadata in Postgres, fetches the object from S3 (with the optional Range
 * header forwarded), and pipes the body straight back to the client with the
 * matching `Accept-Ranges` / `Content-Range` / `Content-Disposition` headers.
 */

import { Hono } from "hono";
import { getDb, schemaIdent } from "../db.ts";
import { verifyMediaToken } from "../http.ts";
import { getExtensionForMime } from "../mime.ts";
import { parseRangeHeader } from "../range.ts";
import { HttpError, type FileType } from "../schemas.ts";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "../sanitize.ts";
import { storageGet, storageGetBytes, storageHead } from "../storage.ts";

/**
 * Maximum body size (bytes) that will be buffered into memory to preserve the
 * Content-Length header. Responses larger than this are streamed with chunked
 * transfer encoding (no Content-Length visible to the client). Applies to both
 * full-file and range requests. 256 MB covers all audio files and typical
 * video exports while keeping per-request peak memory bounded.
 */
const BUFFER_THRESHOLD = 256 * 1024 * 1024;

export const streamRouter = new Hono();

interface StreamRow {
  type: FileType;
  mime_type: string;
  tags: unknown;
  title: string | null;
  canonical_download_title: string | null;
}

function parseTagsValue(value: unknown): string[] {
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

streamRouter.get("/projects/:token/:project/stream/:id", async (c) => {
  const { token, project, id: idRaw } = c.req.param();
  await verifyMediaToken(token);

  const url = new URL(c.req.url);
  const typeRaw = url.searchParams.get("type");
  if (typeRaw !== "audio" && typeRaw !== "video" && typeRaw !== "original" && typeRaw !== "subtitle") {
    throw new HttpError(400, "Type parameter is required");
  }
  const fileType = typeRaw as FileType;

  const decodedId = sanitizeFileId(decodeURIComponent(idRaw));
  if (!decodedId) {
    throw new HttpError(400, "Invalid file ID");
  }

  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<StreamRow[]>(
    `SELECT file.type, file.mime_type, file.tags, file.title,
            COALESCE(designer_target.title, no_overlay_target.title, file.title) AS canonical_download_title
       FROM ${ident}.files AS file
       LEFT JOIN ${ident}.files AS designer_target
         ON designer_target.project = file.project
        AND designer_target.id = file.designer_of_id
        AND designer_target.type = 'video'
       LEFT JOIN LATERAL (
         SELECT candidate.title
           FROM ${ident}.files AS candidate
          WHERE file.type = 'video'
            AND file.media_variant = 'no-overlay'
            AND candidate.project = file.project
            AND candidate.source_id = file.source_id
            AND candidate.type = 'video'
            AND candidate.media_variant = 'pipeline-final'
            AND candidate.visibility = 'active'
          ORDER BY candidate.created_at DESC
          LIMIT 1
       ) AS no_overlay_target ON true
       WHERE file.id = $1 AND file.project = $2 AND file.type = $3`,
    [decodedId, project, fileType],
  );
  const row = rows[0];
  if (!row) {
    throw new HttpError(404, `File '${decodedId}' not found`);
  }
  const tags = parseTagsValue(row.tags);
  if (tags.includes("trash")) {
    throw new HttpError(404, "File is in trash");
  }

  const ext = getExtensionForMime(row.mime_type);
  const head = await storageHead(row.type, project, decodedId, ext);
  if (!head) {
    throw new HttpError(404, `File content not found: ${decodedId}${ext}`);
  }

  const totalSize = head.size;
  const byteRange = parseRangeHeader(c.req.header("range") ?? null, totalSize);

  const safeTitle = sanitizeFilename(normalizeTitle(row.canonical_download_title));
  const downloadFilename = safeTitle ? `${safeTitle}${ext}` : `${decodedId}${ext}`;

  const headers: Record<string, string> = {
    "Accept-Ranges": "bytes",
    "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(downloadFilename)}`,
    "Content-Type": row.mime_type,
  };

  let status = 200;
  if (byteRange) {
    headers["Content-Range"] = `bytes ${byteRange.start}-${byteRange.end}/${totalSize}`;
    headers["Content-Length"] = String(byteRange.end - byteRange.start + 1);
    status = 206;
  } else {
    headers["Content-Length"] = String(totalSize);
  }

  const bodySize = byteRange ? byteRange.end - byteRange.start + 1 : totalSize;

  if (bodySize <= BUFFER_THRESHOLD) {
    const buffer = await storageGetBytes(row.type, project, decodedId, ext, byteRange);
    return new Response(buffer, { status, headers });
  }

  const stream = await storageGet(row.type, project, decodedId, ext, byteRange);
  return new Response(stream, { status, headers });
});
