/** Read-only original-media routes. Uploads use the shared /api/uploads API. */

import { Hono } from "hono";
import { getDb, schemaIdent } from "../db.ts";
import { verifyMediaToken } from "../http.ts";
import { getExtensionForMime } from "../mime.ts";
import { HttpError } from "../schemas.ts";
import { sanitizeFileId, sanitizeFilename } from "../sanitize.ts";
import { presignOriginalDownload } from "../storage.ts";

export const originalsRouter = new Hono();

originalsRouter.get("/projects/:token/:project/api/originals/:id/download", async (c) => {
  const { token, project, id: rawId } = c.req.param(); await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId); if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ mime_type: string; original_filename: string | null; derived_title: string | null; tags: unknown }[]>(
    `SELECT source.mime_type, source.original_filename, source.tags, derived.title AS derived_title
     FROM ${ident}.files AS source
     LEFT JOIN LATERAL (
       SELECT title FROM ${ident}.files AS candidate
       WHERE candidate.project = source.project AND candidate.source_id = source.id
         AND candidate.type IN ('video', 'audio') AND COALESCE(BTRIM(candidate.title), '') <> ''
         AND NOT ((CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb)
       ORDER BY CASE candidate.type WHEN 'video' THEN 0 ELSE 1 END LIMIT 1
     ) AS derived ON TRUE
     WHERE source.id=$1 AND source.project=$2 AND source.type='original'`, [fileId, project],
  );
  const row = rows[0];
  if (!row || (Array.isArray(row.tags) && row.tags.includes("trash"))) throw new HttpError(404, "Original not found");
  const ext = getExtensionForMime(row.mime_type);
  const baseName = sanitizeFilename(row.derived_title ?? row.original_filename ?? fileId) || fileId;
  const filename = baseName.endsWith(ext) ? baseName : `${baseName}${ext}`;
  return c.json({ url: await presignOriginalDownload(project, fileId, ext, filename), expires_in_sec: 300, filename });
});

originalsRouter.get("/projects/:token/:project/api/originals/:id/derived", async (c) => {
  const { token, project, id: rawId } = c.req.param(); await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId); if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb(); const ident = schemaIdent();
  return c.json(await sql.unsafe(
    `SELECT id, project, type, title, tags, duration, file_size, mime_type, source_id, created_at FROM ${ident}.files WHERE project=$1 AND source_id=$2 ORDER BY type, id`, [project, fileId],
  ));
});
