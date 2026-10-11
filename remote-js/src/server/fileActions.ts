/**
 * File update, delete, publish, and bulk audio approval (#59).
 *
 * Same behavior as remote-js/src/routes/files.ts (PUT and DELETE
 * /api/files/:id, POST /api/files/:id/publish, POST /api/audio/approve-pending).
 * The route handler checks the media token before it calls these functions.
 */

import { getDb, schemaIdent } from "./db.ts";
import { HttpError, json } from "./http.ts";
import { parseTagsValue } from "./fileMetadata.ts";
import { getExtensionForMime } from "./mime.ts";
import { sanitizeFileId } from "./sanitize.ts";
import { validateAudioTags, validateVideoTags, type FileType } from "./schemas.ts";
import { storageDelete, storageDeleteAnyExtension } from "./storage.ts";
import { visibilitySql } from "./videoSql.ts";

function fileTypeParam(request: Request): FileType {
  const type = new URL(request.url).searchParams.get("type");
  if (type !== "audio" && type !== "video" && type !== "original") {
    throw new HttpError(400, "Type parameter is required");
  }
  return type;
}

function fileIdParam(idRaw: string): string {
  const id = sanitizeFileId(idRaw);
  if (!id) throw new HttpError(400, "Invalid file ID");
  return id;
}

function notFoundText(id: string, type: FileType): string {
  return `File '${id}' of type '${type}' not found`;
}

/** PUT /api/files/:id?type=... - set the tags and (optional) the title. */
export async function updateFile(request: Request, project: string, idRaw: string): Promise<Response> {
  const fileType = fileTypeParam(request);
  const id = fileIdParam(idRaw);

  const body = (await request.json().catch(() => null)) as { tags?: unknown; title?: unknown } | null;
  if (!body || !Array.isArray(body.tags)) {
    throw new HttpError(400, "Body must include tags array");
  }
  let tags = body.tags.map(String);
  const title: string | null | undefined =
    body.title === undefined ? undefined : body.title === null ? null : String(body.title);

  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ type: FileType }[]>(
    `SELECT type FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
    [id, project, fileType],
  );
  if (rows.length === 0) throw new HttpError(404, notFoundText(id, fileType));
  const rowType = rows[0]!.type;

  if (rowType === "audio") tags = validateAudioTags(tags);
  else if (rowType === "video") tags = validateVideoTags(tags);
  if (tags.length === 0 && rowType === "audio") tags = ["todo"];

  // The tags are JSON text. A `$1::jsonb` parameter makes postgres.js encode
  // the text again, so the row gets a JSON string and the CASE tests fail.
  await sql.begin(async (tx) => {
    if (title !== undefined) {
      await tx.unsafe(
        `UPDATE ${ident}.files
           SET tags = $1::text::jsonb, title = $2,
               visibility = CASE WHEN $1::text::jsonb @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END,
               review_status = CASE WHEN $5 = 'audio' THEN CASE WHEN $1::text::jsonb @> '["ready"]'::jsonb THEN 'approved' ELSE 'todo' END ELSE review_status END
           WHERE id = $3 AND project = $4 AND type = $5`,
        [JSON.stringify(tags), title, id, project, rowType],
      );
    } else {
      await tx.unsafe(
        `UPDATE ${ident}.files
           SET tags = $1::text::jsonb,
               visibility = CASE WHEN $1::text::jsonb @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END,
               review_status = CASE WHEN $4 = 'audio' THEN CASE WHEN $1::text::jsonb @> '["ready"]'::jsonb THEN 'approved' ELSE 'todo' END ELSE review_status END
           WHERE id = $2 AND project = $3 AND type = $4`,
        [JSON.stringify(tags), id, project, rowType],
      );
    }
  });

  return json({ ok: true, id, tags, title: title ?? null });
}

/**
 * DELETE /api/files/:id?type=... - only for a file with the `trash` tag.
 * Deletes the S3 object, marks open source-processing jobs of this source ID
 * stale, and deletes the row (the last two in one transaction).
 */
export async function deleteFile(request: Request, project: string, idRaw: string): Promise<Response> {
  const fileType = fileTypeParam(request);
  const id = fileIdParam(idRaw);

  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ type: FileType; tags: unknown; mime_type: string }[]>(
    `SELECT file.type, file.tags, file.mime_type
       FROM ${ident}.files AS file
       WHERE file.id = $1 AND file.project = $2 AND file.type = $3`,
    [id, project, fileType],
  );
  if (rows.length === 0) throw new HttpError(404, notFoundText(id, fileType));
  const row = rows[0]!;
  if (!parseTagsValue(row.tags).includes("trash")) {
    throw new HttpError(400, "Only trashed files can be deleted. Add 'trash' tag first.");
  }

  try {
    await storageDelete(row.type, project, id, getExtensionForMime(row.mime_type));
  } catch {
    await storageDeleteAnyExtension(row.type, project, id);
  }

  // A deleted original makes its open source-processing work stale. Keep
  // this change with the row delete, so that a worker cannot resume a
  // waiting job after its source is gone.
  await sql.begin(async (tx) => {
    await tx.unsafe(
      `UPDATE ${ident}.source_processing
          SET state='stale', lease_token=NULL, lease_until=NULL,
              waiting_reason=NULL, last_error='original deleted', updated_at=now()
        WHERE project=$1 AND source_id=$2
          AND state IN ('pending', 'claimed', 'waiting')`,
      [project, id],
    );
    await tx.unsafe(
      `DELETE FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
      [id, project, row.type],
    );
  });

  return json({ ok: true, id, deleted: true });
}

/** POST /api/files/:id/publish - mark an active video as published. */
export async function publishFile(project: string, idRaw: string): Promise<Response> {
  const id = fileIdParam(idRaw);
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(
    `UPDATE ${ident}.files AS card
        SET publication_status='published'
      WHERE card.id=$1 AND card.project=$2 AND card.type='video'
        AND ${visibilitySql("card")} = 'active'
      RETURNING card.id`,
    [id, project],
  );
  if (rows.length === 0) throw new HttpError(404, "Active video not found");
  return json({ ok: true, id, publication_status: "published" });
}

/**
 * POST /api/audio/approve-pending - body `{confirm: true}`. Approves all
 * audio with the `todo` tag and no `trash` tag (the tag list becomes
 * `["ready"]`). It does not check for empty titles.
 */
export async function approvePendingAudio(request: Request, project: string): Promise<Response> {
  const body = (await request.json().catch(() => null)) as { confirm?: unknown } | null;
  if (body?.confirm !== true) throw new HttpError(400, "Explicit confirmation is required");
  const sql = getDb();
  const ident = schemaIdent();
  const tags = "(CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END)";
  const rows = await sql.unsafe<{ id: string }[]>(
    `UPDATE ${ident}.files
        SET tags = '["ready"]'::jsonb, review_status = 'approved', visibility = COALESCE(visibility, 'active')
      WHERE project = $1
        AND type = 'audio'
        AND ${tags} @> '["todo"]'::jsonb
        AND NOT (${tags} @> '["trash"]'::jsonb)
      RETURNING id`,
    [project],
  );
  return json({ ok: true, approved_count: rows.length });
}
