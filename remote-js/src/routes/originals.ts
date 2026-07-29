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
  const rows = await sql.unsafe<{ mime_type: string; original_filename: string | null; tags: unknown }[]>(
    `SELECT mime_type, original_filename, tags FROM ${ident}.files WHERE id=$1 AND project=$2 AND type='original'`, [fileId, project],
  );
  const row = rows[0];
  if (!row || (Array.isArray(row.tags) && row.tags.includes("trash"))) throw new HttpError(404, "Original not found");
  const filename = sanitizeFilename(row.original_filename ?? fileId) || fileId;
  return c.json({ url: await presignOriginalDownload(project, fileId, getExtensionForMime(row.mime_type), filename), expires_in_sec: 300, filename });
});

originalsRouter.get("/projects/:token/:project/api/originals/:id/derived", async (c) => {
  const { token, project, id: rawId } = c.req.param(); await verifyMediaToken(token);
  const fileId = sanitizeFileId(rawId); if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb(); const ident = schemaIdent();
  return c.json(await sql.unsafe(
    `SELECT id, project, type, title, tags, duration, file_size, mime_type, source_id, created_at FROM ${ident}.files WHERE project=$1 AND source_id=$2 ORDER BY type, id`, [project, fileId],
  ));
});
