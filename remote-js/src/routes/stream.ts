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
import { storageGet, storageHead } from "../storage.ts";

export const streamRouter = new Hono();

interface StreamRow {
  type: FileType;
  mime_type: string;
  tags: unknown;
  title: string | null;
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
  if (typeRaw !== "audio" && typeRaw !== "video") {
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
    `SELECT type, mime_type, tags, title
       FROM ${ident}.files
       WHERE id = $1 AND project = $2 AND type = $3`,
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

  const safeTitle = sanitizeFilename(normalizeTitle(row.title));
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

  const fetched = await storageGet(
    row.type,
    project,
    decodedId,
    ext,
    byteRange,
    totalSize,
  );

  return new Response(fetched.body, { status, headers });
});
