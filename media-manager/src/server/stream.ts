/**
 * GET /projects/:token/:project/stream/:id?type=audio|video|original
 *
 * Range-aware S3 streaming, ported from remote-js/src/routes/stream.ts with
 * the same checks, SQL, and headers:
 *
 * - `type` is necessary (400). The ID is URL-decoded one more time (QUIRK:
 *   the router already decoded it) and then sanitized (400 when empty).
 * - No row: 404. A row with the "trash" tag: 404 (tag test only).
 * - No S3 object: 404.
 * - `Range: bytes=...` (first range only) gives 206 with `Content-Range`.
 *   A range that the object cannot satisfy is ignored: the response is the
 *   full 200 (not 416), as before.
 * - `Content-Disposition: inline` with the canonical title. A designer
 *   revision downloads with the title of its no-overlay card.
 * - A body of 256 MiB or less is read into memory first (as before). A
 *   larger body streams from S3 to the client and is never held in memory.
 *   Node.js keeps the Content-Length header in both cases.
 * - HEAD gives the same status and headers (also Content-Length) with no
 *   body, and does not read the object. server.ts keeps this Content-Length
 *   because the response has Accept-Ranges (the old server did the same).
 */

import { getDb, schemaIdent } from "./db.ts";
import { getExtensionForMime } from "./mime.ts";
import { parseRangeHeader } from "./range.ts";
import { HttpError, type FileType } from "./schemas.ts";
import { normalizeTitle, sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import { storageGet, storageGetBytes, storageHead } from "./storage.ts";

/** Bodies up to this size are buffered so that a body error gives a 500. */
const BUFFER_THRESHOLD = 256 * 1024 * 1024;

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

export async function streamFile(request: Request, project: string, idRaw: string): Promise<Response> {
  const url = new URL(request.url);
  const typeRaw = url.searchParams.get("type");
  if (typeRaw !== "audio" && typeRaw !== "video" && typeRaw !== "original") {
    throw new HttpError(400, "Type parameter is required");
  }
  const fileType: FileType = typeRaw;

  // QUIRK: a second decode. A bad escape ("%") throws URIError -> 500, as before.
  const decodedId = sanitizeFileId(decodeURIComponent(idRaw));
  if (!decodedId) {
    throw new HttpError(400, "Invalid file ID");
  }

  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<StreamRow[]>(
    `SELECT file.type, file.mime_type, file.tags, file.title,
            -- A designer revision and its no-overlay card download with the
            -- approved title of that card.
            CASE WHEN designer_target.id IS NOT NULL THEN designer_target.title
                 ELSE file.title END AS canonical_download_title
       FROM ${ident}.files AS file
       LEFT JOIN ${ident}.files AS designer_target
         ON designer_target.project = file.project
        AND designer_target.id = file.designer_of_id
        AND designer_target.type = 'video'
       WHERE file.id = $1 AND file.project = $2 AND file.type = $3`,
    [decodedId, project, fileType],
  );
  const row = rows[0];
  if (!row) {
    throw new HttpError(404, `File '${decodedId}' not found`);
  }
  if (parseTagsValue(row.tags).includes("trash")) {
    throw new HttpError(404, "File is in trash");
  }

  const ext = getExtensionForMime(row.mime_type);
  const head = await storageHead(row.type, project, decodedId, ext);
  if (!head) {
    throw new HttpError(404, `File content not found: ${decodedId}${ext}`);
  }

  const totalSize = head.size;
  const byteRange = parseRangeHeader(request.headers.get("range"), totalSize);

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

  if (request.method === "HEAD") {
    return new Response(null, { status, headers });
  }

  const bodySize = byteRange ? byteRange.end - byteRange.start + 1 : totalSize;
  if (bodySize <= BUFFER_THRESHOLD) {
    const buffer = await storageGetBytes(row.type, project, decodedId, ext, byteRange);
    return new Response(buffer as Uint8Array<ArrayBuffer>, { status, headers });
  }

  // Large body: pipe the S3 stream. When the client goes away, Next.js
  // cancels this stream, which closes the S3 connection.
  const stream = await storageGet(row.type, project, decodedId, ext, byteRange);
  return new Response(stream, { status, headers });
}
