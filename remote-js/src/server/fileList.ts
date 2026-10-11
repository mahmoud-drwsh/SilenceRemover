/**
 * GET /projects/:token/:project/api/files (the file list).
 *
 * Ported without change from the old Bun service file routes/files.ts: the same query
 * parameters, the same order of checks, the same SQL (the lateral joins and
 * the count query use the same WHERE clause), and the same paging headers
 * (`X-Has-More`, and `X-Total-Count` only at offset 0).
 */

import { getDb, schemaIdent } from "./db.ts";
import { json } from "./http.ts";
import { HttpError, type FileType } from "./schemas.ts";
import { normalizeTitle, sanitizeFileId } from "./sanitize.ts";
import { rowToResponse, type FileRow } from "./fileResponse.ts";
import { normalizedTagsSql, videoVariantSql, visibilitySql } from "./videoSql.ts";

/** Virtual video views. Removed view names (#44) fall back to All. */
export const VIDEO_VIEWS: ReadonlySet<string> = new Set(["all", "needs-designer", "designer", "pending", "trash"]);
export const REMOVED_VIDEO_VIEWS: ReadonlySet<string> = new Set(["pipeline-final", "no-overlay"]);

type SqlParam = string | number | boolean | null | string[];

function parseTagsParam(value: string | undefined): string[] | null {
  if (!value) return null;
  const split = value
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  return split.length > 0 ? split : null;
}

function addTagListConditions(args: {
  conditions: string[];
  params: SqlParam[];
  tagList: string[] | null;
  includeTrash: boolean;
  excludedTags?: string[];
}): void {
  const tagsSql =
    "CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END";

  if (args.tagList) {
    for (const tag of args.tagList) {
      args.params.push([tag]);
      args.conditions.push(`${tagsSql} @> CAST($${args.params.length} AS jsonb)`);
    }
  } else if (!args.includeTrash) {
    args.params.push(["trash"]);
    args.conditions.push(`NOT (${tagsSql} @> CAST($${args.params.length} AS jsonb))`);
  }

  for (const tag of args.excludedTags ?? []) {
    args.params.push([tag]);
    args.conditions.push(`NOT (${tagsSql} @> CAST($${args.params.length} AS jsonb))`);
  }
}

/**
 * Answer one file-list request. `include_pending` is read by the old route
 * but has no effect, so it is not read here.
 */
export async function listFiles(project: string, url: URL): Promise<Response> {
  const typeParam = url.searchParams.get("type") as FileType | null;
  const tagsParam = url.searchParams.get("tags") ?? undefined;
  const requestedView = url.searchParams.get("view") ?? undefined;
  const sort = url.searchParams.get("sort") ?? "asc";
  const limitParam = url.searchParams.get("limit");
  const offsetParam = url.searchParams.get("offset");
  const checkId = url.searchParams.get("check_id");
  const checkTitle = url.searchParams.get("check_title");
  const includeTrashParam = url.searchParams.get("include_trash") === "true";
  const designerMissing = url.searchParams.get("designer_missing") === "true";

  // A bookmark or an old cached page can still send a removed view name.
  const view = requestedView && REMOVED_VIDEO_VIEWS.has(requestedView) ? "all" : requestedView;
  // The Trash view shows trashed items, so it cannot also hide them.
  const includeTrash = includeTrashParam || view === "trash";
  if (view && !VIDEO_VIEWS.has(view) && view !== "todo" && view !== "approved") {
    throw new HttpError(400, "Invalid view parameter");
  }

  if (typeParam && typeParam !== "audio" && typeParam !== "video" && typeParam !== "original") {
    throw new HttpError(400, "Invalid type parameter");
  }

  let pageSize: number | null = null;
  let pageOffset = 0;
  if (limitParam !== null) {
    pageSize = Number(limitParam);
    if (!Number.isSafeInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new HttpError(400, "limit must be an integer between 1 and 100");
    }
    if (offsetParam !== null) {
      pageOffset = Number(offsetParam);
      if (!Number.isSafeInteger(pageOffset) || pageOffset < 0) {
        throw new HttpError(400, "offset must be a non-negative integer");
      }
    }
  } else if (offsetParam !== null) {
    throw new HttpError(400, "offset requires limit");
  }

  const sql = getDb();
  const ident = schemaIdent();

  // Pre-flight check mode: check_id provided.
  if (checkId !== null) {
    const sanitizedId = sanitizeFileId(checkId);
    if (!sanitizedId) {
      throw new HttpError(400, "Invalid check_id");
    }
    if (!typeParam) {
      throw new HttpError(400, "Type parameter is required when using check_id");
    }

    const rows = await sql.unsafe<FileRow[]>(
      `SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at, source_id, original_filename, checksum_sha256, NULL::text AS derived_title, NULL::text AS designer_video_id, NULL::text AS active_designer_revision_id, designer_of_id, media_variant, review_status, visibility, publication_status
       FROM ${ident}.files WHERE id = $1 AND project = $2 AND type = $3`,
      [sanitizedId, project, typeParam],
    );
    const row = rows[0];

    if (row) {
      const existingTitle = normalizeTitle(row.title);
      const response = rowToResponse(row);
      if (checkTitle !== null) {
        const checkTitleNormalized = normalizeTitle(checkTitle);
        return json([
          {
            ...response,
            exists: true,
            would_overwrite: existingTitle !== checkTitleNormalized,
            existing_title: existingTitle,
            provided_title: checkTitleNormalized,
          },
        ]);
      }
      return json([response]);
    }

    return json([{ exists: false, id: sanitizedId, type: typeParam, project }]);
  }

  // Normal list mode.
  const tagList = parseTagsParam(tagsParam);

  const conditions: string[] = ["project = $1"];
  const params: SqlParam[] = [project];

  if (typeParam) {
    params.push(typeParam);
    conditions.push(`type = $${params.length}`);
  } else {
    // Old subtitle rows can still be in the database.
    conditions.push("type IN ('audio', 'video', 'original')");
  }

  // The no-overlay video is the canonical card. A designer revision is a
  // linked presentation of that card, not a list item in its own right.
  if (typeParam === "video") {
    conditions.push("source.designer_of_id IS NULL");
    conditions.push("source.id NOT LIKE '%-designer'");
    conditions.push(`${videoVariantSql("source")} = 'no-overlay'`);
  }

  if (designerMissing) {
    if (typeParam !== "video") throw new HttpError(400, "designer_missing requires type=video");
    conditions.push(`NOT EXISTS (
      SELECT 1 FROM ${ident}.files AS designer_candidate
      WHERE designer_candidate.project = source.project
        AND designer_candidate.type = 'video'
        AND designer_candidate.designer_of_id = source.id
        AND NOT (${normalizedTagsSql("designer_candidate")} @> '["trash"]'::jsonb)
    )`);
  }

  // Virtual views are relationship and state queries. Designer links use
  // the index files (project, designer_of_id).
  const visibilityExpr = visibilitySql("source");
  const publicationExpr = `COALESCE(source.publication_status, CASE WHEN ${normalizedTagsSql("source")} @> '["pending"]'::jsonb THEN 'pending' WHEN source.type='video' THEN 'published' ELSE NULL END)`;
  const reviewExpr = `COALESCE(source.review_status, CASE WHEN ${normalizedTagsSql("source")} @> '["ready"]'::jsonb THEN 'approved' WHEN source.type='audio' THEN 'todo' ELSE NULL END)`;
  if (view === "trash") conditions.push(`${visibilityExpr} = 'trash'`);
  if (view === "pending") conditions.push(`${publicationExpr} = 'pending'`);
  if (view === "todo") conditions.push(`COALESCE(${reviewExpr}, 'todo') = 'todo'`);
  if (view === "approved") conditions.push(`COALESCE(${reviewExpr}, 'todo') = 'approved'`);
  if (view === "needs-designer") conditions.push(`NOT EXISTS (
    SELECT 1 FROM ${ident}.files candidate WHERE candidate.project=source.project
      AND candidate.designer_of_id=source.id AND candidate.type='video'
      AND COALESCE(candidate.visibility, CASE WHEN ${normalizedTagsSql("candidate")} @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END) <> 'trash'
  )`);
  if (view === "designer") conditions.push(`EXISTS (
    SELECT 1 FROM ${ident}.files candidate WHERE candidate.project=source.project
      AND candidate.designer_of_id=source.id AND candidate.type='video'
  )`);

  addTagListConditions({
    conditions,
    params,
    tagList,
    includeTrash,
    // Legacy no-overlay rows carry a "no-overlay" tag, so only the designer
    // tag stays excluded for video lists.
    excludedTags: typeParam === "video" ? ["designer"] : [],
  });

  const whereClause = conditions.join(" AND ");
  const sortDirection = sort === "asc" ? "ASC" : "DESC";

  let pageClause = "";
  if (pageSize !== null) {
    // Fetch one extra row so that callers know whether to request another
    // page without transferring the full virtual view.
    params.push(pageSize + 1);
    const limitPosition = params.length;
    params.push(pageOffset);
    const offsetPosition = params.length;
    pageClause = ` LIMIT $${limitPosition} OFFSET $${offsetPosition}`;
  }

  const rowsPromise = sql.unsafe<FileRow[]>(
    `SELECT source.id, source.project, source.type, source.title, source.tags, source.duration, source.file_size, source.mime_type, source.created_at, source.source_id, source.original_filename, source.checksum_sha256, derived.title AS derived_title, designer.id AS designer_video_id, active_designer.id AS active_designer_revision_id, source.designer_of_id,
       ${videoVariantSql("source")} AS media_variant,
       ${reviewExpr} AS review_status,
       ${visibilityExpr} AS visibility,
       ${publicationExpr} AS publication_status,
       review.id AS review_audio_id
     FROM ${ident}.files AS source
     LEFT JOIN LATERAL (
       SELECT title
       FROM ${ident}.files AS candidate
       WHERE candidate.project = source.project
         AND candidate.source_id = source.id
         AND candidate.type IN ('video', 'audio')
         AND COALESCE(BTRIM(candidate.title), '') <> ''
         AND candidate.designer_of_id IS NULL
         AND candidate.id NOT LIKE '%-designer'
         AND NOT ((CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb)
       ORDER BY CASE candidate.type WHEN 'video' THEN 0 ELSE 1 END,
         CASE WHEN (CASE WHEN jsonb_typeof(candidate.tags) = 'string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["no-overlay"]'::jsonb THEN 1 ELSE 0 END
       LIMIT 1
     ) AS derived ON TRUE
     LEFT JOIN LATERAL (
       SELECT CASE WHEN source.type = 'video' THEN source.active_designer_revision_id END AS id
     ) AS active_designer ON TRUE
     LEFT JOIN LATERAL (
       SELECT candidate.id
       FROM ${ident}.files AS candidate
       WHERE source.type = 'video'
         AND active_designer.id IS NOT NULL
         AND candidate.project = source.project
         AND candidate.id = active_designer.id
         AND candidate.type = 'video'
         AND NOT (${normalizedTagsSql("candidate")} @> '["trash"]'::jsonb)
       UNION ALL
       SELECT newest.id FROM (
         SELECT candidate.id
         FROM ${ident}.files AS candidate
         WHERE source.type = 'video'
           AND active_designer.id IS NULL
           AND candidate.project = source.project
           AND candidate.designer_of_id = source.id
           AND candidate.type = 'video'
           AND NOT (${normalizedTagsSql("candidate")} @> '["trash"]'::jsonb)
         ORDER BY candidate.created_at DESC, candidate.id
         LIMIT 1
       ) AS newest
       LIMIT 1
     ) AS designer ON TRUE
     LEFT JOIN LATERAL (
       SELECT candidate.id FROM ${ident}.files AS candidate
       WHERE source.type='video' AND candidate.project=source.project AND candidate.type='audio'
         AND candidate.source_id=COALESCE(source.source_id,source.id)
         AND COALESCE(candidate.visibility, CASE WHEN (CASE WHEN jsonb_typeof(candidate.tags)='string' THEN (candidate.tags #>> '{}')::jsonb ELSE candidate.tags END) @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END) <> 'trash'
       ORDER BY candidate.created_at DESC LIMIT 1
     ) AS review ON TRUE
     WHERE ${whereClause}
     ORDER BY source.id ${sortDirection}${pageClause}`,
    params,
  );

  const countPromise = pageSize !== null && pageOffset === 0
    ? sql.unsafe<{ total: string }[]>(
      `SELECT COUNT(*)::text AS total FROM ${ident}.files AS source WHERE ${whereClause}`,
      params.slice(0, params.length - 2),
    )
    : Promise.resolve(null);
  const [rows, countRows] = await Promise.all([rowsPromise, countPromise]);
  const hasMore = pageSize !== null && rows.length > pageSize;
  const visibleRows = pageSize !== null && hasMore ? rows.slice(0, pageSize) : rows;
  const headers: Record<string, string> = {};
  if (pageSize !== null) {
    headers["X-Has-More"] = String(hasMore);
    if (countRows?.[0]) headers["X-Total-Count"] = countRows[0].total;
  }
  return json(visibleRows.map(rowToResponse), 200, headers);
}
