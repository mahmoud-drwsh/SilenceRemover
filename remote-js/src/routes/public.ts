import { Hono } from "hono";
import { join } from "node:path";
import { getDb, schemaIdent } from "../db.ts";
import { getExtensionForMime } from "../mime.ts";
import { parseRangeHeader } from "../range.ts";
import { HttpError } from "../schemas.ts";
import { normalizeTitle, sanitizeFilename, sanitizeFileId } from "../sanitize.ts";
import { storageGet, storageGetBytes, storageHead } from "../storage.ts";
import { verifyPublicShareLink } from "../shareLinks.ts";

export const publicRouter = new Hono();
const PUBLIC_HTML = join(new URL("../../frontend/", import.meta.url).pathname, "public.html");
const BUFFER_THRESHOLD = 256 * 1024 * 1024;

function parseTags(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === "string") {
    try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed.map(String) : []; } catch { return []; }
  }
  return [];
}

async function servePublicPage() {
  return new Response(Bun.file(PUBLIC_HTML), { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

publicRouter.get("/public/:share_token", servePublicPage);
publicRouter.get("/public/:share_token/", servePublicPage);

publicRouter.get("/public/:share_token/api/videos", async (c) => {
  const project = await verifyPublicShareLink(c.req.param("share_token"));
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<any[]>(
    `SELECT id, title, duration, file_size, mime_type, created_at, tags
       FROM ${ident}.files
      WHERE project = $1 AND type = 'video'
        AND NOT (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> '["trash"]'::jsonb)
        AND NOT (CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> '["pending"]'::jsonb)
        AND (
          CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> '["FB"]'::jsonb
          OR CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END @> '["TT"]'::jsonb
        )
      ORDER BY created_at DESC, id ASC`,
    [project],
  );
  return c.json({
    project,
    videos: rows.map((row) => ({
      id: row.id,
      title: row.title || row.id,
      duration: Number(row.duration || 0),
      file_size: Number(row.file_size || 0),
      mime_type: row.mime_type,
      created_at: row.created_at instanceof Date ? row.created_at.toISOString() : String(row.created_at || ""),
      stream_url: `/public/${encodeURIComponent(c.req.param("share_token"))}/stream/${encodeURIComponent(row.id)}`,
    })),
  });
});

publicRouter.get("/public/:share_token/stream/:id", async (c) => {
  const project = await verifyPublicShareLink(c.req.param("share_token"));
  const id = sanitizeFileId(decodeURIComponent(c.req.param("id")));
  if (!id) throw new HttpError(400, "Invalid file ID");
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<any[]>(
    `SELECT id, title, mime_type, tags FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = 'video'`,
    [id, project],
  );
  const row = rows[0];
  const tags = row ? parseTags(row.tags) : [];
  if (!row || tags.includes("trash") || tags.includes("pending") || (!tags.includes("FB") && !tags.includes("TT"))) {
    throw new HttpError(404, "Video not found");
  }
  const ext = getExtensionForMime(row.mime_type);
  const head = await storageHead("video", project, id, ext);
  if (!head) throw new HttpError(404, "Video content not found");
  const range = parseRangeHeader(c.req.header("range") ?? null, head.size);
  const bodySize = range ? range.end - range.start + 1 : head.size;
  const headers: Record<string, string> = {
    "Accept-Ranges": "bytes",
    "Content-Type": row.mime_type,
    "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(`${sanitizeFilename(normalizeTitle(row.title)) || id}${ext}`)}`,
    "Content-Length": String(bodySize),
  };
  if (range) headers["Content-Range"] = `bytes ${range.start}-${range.end}/${head.size}`;
  const status = range ? 206 : 200;
  if (bodySize <= BUFFER_THRESHOLD) return new Response(await storageGetBytes("video", project, id, ext, range), { status, headers });
  return new Response(await storageGet("video", project, id, ext, range), { status, headers });
});
