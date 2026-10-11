/**
 * Read-only original routes, ported from the old Bun service file routes/originals.ts
 * with the same SQL, checks, and response shapes. Uploads use the shared
 * upload-session API.
 *
 *   GET /projects/:token/:project/api/originals/:id/download
 *   GET /projects/:token/:project/api/originals/:id/derived
 */

import { getDb, schemaIdent } from "./db.ts";
import { json } from "./http.ts";
import { getExtensionForMime } from "./mime.ts";
import { HttpError } from "./schemas.ts";
import { sanitizeFileId, sanitizeFilename } from "./sanitize.ts";
import { presignOriginalDownload } from "./storage.ts";

/**
 * A presigned S3 GET URL (300 s) with an attachment filename. The filename
 * is the title of the derived video (else the review audio), else the
 * original filename, else the ID. There is no S3 existence check.
 */
export async function originalDownload(project: string, rawId: string): Promise<Response> {
  const fileId = sanitizeFileId(rawId);
  if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ mime_type: string; original_filename: string | null; derived_title: string | null; tags: unknown }[]>(
    `SELECT source.mime_type, source.original_filename, source.tags, derived.title AS derived_title
     FROM ${ident}.files AS source
     LEFT JOIN LATERAL (
       SELECT title FROM ${ident}.files AS candidate
       WHERE candidate.project = source.project AND candidate.source_id = source.id
         AND candidate.type IN ('video', 'audio') AND COALESCE(BTRIM(candidate.title), '') <> ''
         AND candidate.designer_of_id IS NULL
         AND candidate.id NOT LIKE '%-designer'
         AND NOT ((CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb)
       ORDER BY CASE candidate.type WHEN 'video' THEN 0 ELSE 1 END,
         CASE WHEN (CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["no-overlay"]'::jsonb THEN 1 ELSE 0 END
       LIMIT 1
     ) AS derived ON TRUE
     WHERE source.id=$1 AND source.project=$2 AND source.type='original'`,
    [fileId, project],
  );
  const row = rows[0];
  // QUIRK: only a JSON array is checked for "trash" (not a legacy string list).
  if (!row || (Array.isArray(row.tags) && row.tags.includes("trash"))) {
    throw new HttpError(404, "Original not found");
  }
  const ext = getExtensionForMime(row.mime_type);
  const baseName = sanitizeFilename(row.derived_title ?? row.original_filename ?? fileId) || fileId;
  const filename = baseName.endsWith(ext) ? baseName : `${baseName}${ext}`;
  return json({ url: await presignOriginalDownload(project, fileId, ext, filename), expires_in_sec: 300, filename });
}

/**
 * The raw rows that have this original as `source_id`. QUIRK: this includes
 * trashed rows and designer revisions; `file_size` is a string (bigint) and
 * `tags` is the stored JSON value. An unknown ID gives [].
 */
export async function originalDerived(project: string, rawId: string): Promise<Response> {
  const fileId = sanitizeFileId(rawId);
  if (!fileId) throw new HttpError(400, "Invalid original ID");
  const sql = getDb();
  const ident = schemaIdent();
  return json(await sql.unsafe(
    `SELECT id, project, type, title, tags, duration, file_size, mime_type, source_id, created_at FROM ${ident}.files WHERE project=$1 AND source_id=$2 ORDER BY type, id`,
    [project, fileId],
  ));
}
