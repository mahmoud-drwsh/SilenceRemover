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
  validateVideoTags,
} from "../schemas.ts";
import { normalizeTitle, sanitizeFileId } from "../sanitize.ts";
import {
  storageDelete,
  storageDeleteAnyExtension,
  storagePutBytes,
} from "../storage.ts";
import { probeDurationSeconds } from "../ffprobe.ts";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { once } from "node:events";
import { rehearseOriginalRootedBackfill } from "../originalRootedRehearsal.ts";
import {
  cardTitleNeedsLegacySql,
  legacyOverlaidMatchSql,
  legacyOverlaidOrderSql,
  normalizedTagsSql,
  publicationStatusSql,
  videoVariantSql,
  visibilitySql,
} from "../videoSql.ts";

export const filesRouter = new Hono();

/** Report-only production rehearsal; there is intentionally no HTTP apply route. */
filesRouter.get("/projects/:token/:project/api/original-rooted-rehearsal", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);
  return c.json(await rehearseOriginalRootedBackfill(project));
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
  designer_video_id: string | null;
  active_designer_revision_id: string | null;
  designer_of_id: string | null;
  media_variant: string | null;
  review_status: string | null;
  visibility: string | null;
  publication_status: string | null;
  review_audio_id: string | null;
}

export type MediaAttributes = {
  mediaVariant: "pipeline-final" | "no-overlay" | "designer" | null;
  reviewStatus: "todo" | "approved" | null;
  visibility: "active" | "trash";
  publicationStatus: "pending" | "published" | null;
};

/**
 * Compatibility bridge only: existing tags remain untouched. New writes use
 * the explicit attributes, and reads coalesce these values for legacy rows.
 */
export function legacyMediaAttributes(
  type: FileType,
  tags: string[],
  designerOfId: string | null = null,
): MediaAttributes {
  const visibility = tags.includes("trash") ? "trash" : "active";
  const mediaVariant = type !== "video" ? null
    : designerOfId || tags.includes("designer") ? "designer"
      : tags.includes("no-overlay") ? "no-overlay"
        : "pipeline-final";
  const reviewStatus = type !== "audio" ? null
    : tags.includes("ready") ? "approved" : "todo";
  const publicationStatus = type !== "video" ? null
    : tags.includes("pending") ? "pending" : "published";
  return { mediaVariant, reviewStatus, visibility, publicationStatus };
}

function rowToResponse(row: FileRow): FileResponse {
  const legacy = legacyMediaAttributes(row.type, parseTagsValue(row.tags), row.designer_of_id);
  const mediaVariant = row.media_variant === "pipeline-final" || row.media_variant === "no-overlay" || row.media_variant === "designer"
    ? row.media_variant : legacy.mediaVariant;
  const reviewStatus = row.review_status === "todo" || row.review_status === "approved" ? row.review_status : legacy.reviewStatus;
  const visibility = row.visibility === "trash" ? "trash" : row.visibility === "active" ? "active" : legacy.visibility;
  const publicationStatus = row.publication_status === "pending" || row.publication_status === "published"
    ? row.publication_status : legacy.publicationStatus;
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
    designer_video_id: row.designer_video_id ?? null,
    active_designer_revision_id: row.active_designer_revision_id ?? null,
    designer_of_id: row.designer_of_id ?? null,
    media_variant: mediaVariant,
    review_status: reviewStatus,
    visibility,
    publication_status: publicationStatus,
    review_audio_id: row.review_audio_id ?? null,
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
  } else if (fileType === "video") {
    tags = validateVideoTags(tags);
  }

  if (tags.length === 0 && fileType === "audio") {
    tags = ["todo"];
  }
  return tags;
}

export async function assertSourceOriginalExists(project: string, sourceId: string | null): Promise<void> {
  if (!sourceId) throw new HttpError(400, "Derived media must include source_id for its original");
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
  attributes?: Partial<MediaAttributes>;
}): Promise<void> {
  const sql = getDb();
  const ident = schemaIdent();
  const attributes = { ...legacyMediaAttributes(args.fileType, args.tagList, args.designerOfId ?? null), ...args.attributes };

  try {
    await sql.begin(async (tx) => {
      await tx.unsafe(
      `INSERT INTO ${ident}.files
         (id, project, type, title, tags, duration, file_size, mime_type, source_id, original_filename, checksum_sha256, designer_of_id, media_variant, review_status, visibility, publication_status)
       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
       ON CONFLICT (id, project, type) DO UPDATE SET
         title=EXCLUDED.title, tags=EXCLUDED.tags, duration=EXCLUDED.duration,
         file_size=EXCLUDED.file_size, mime_type=EXCLUDED.mime_type,
         source_id=EXCLUDED.source_id, original_filename=EXCLUDED.original_filename,
         checksum_sha256=EXCLUDED.checksum_sha256, designer_of_id=EXCLUDED.designer_of_id,
         media_variant=EXCLUDED.media_variant, review_status=EXCLUDED.review_status,
         visibility=EXCLUDED.visibility, publication_status=EXCLUDED.publication_status`,
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
        attributes.mediaVariant ?? null,
        attributes.reviewStatus ?? null,
        attributes.visibility,
        attributes.publicationStatus ?? null,
      ],
      );
      // Completion of a new designer revision is the only operation that
      // advances the active pointer. Older revision records remain untouched.
      if (args.fileType === "video" && args.designerOfId) {
        await tx.unsafe(
          `UPDATE ${ident}.files
             SET active_designer_revision_id=$1
           WHERE id=$2 AND project=$3 AND type='video'`,
          [args.fileId, args.designerOfId, args.project],
        );
      }
    });
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
  /** Changes the `trash` tag condition, for example to use the card state. */
  trashCondition?: (tagCondition: string) => string;
}): void {
  const normalizedTagsSql =
    "CASE WHEN jsonb_typeof(tags) = 'string' THEN (tags #>> '{}')::jsonb ELSE tags END";
  const trashCondition = args.trashCondition ?? ((tagCondition: string) => tagCondition);

  if (args.tagList) {
    for (const tag of args.tagList) {
      args.params.push([tag]);
      const tagCondition = `${normalizedTagsSql} @> CAST($${args.params.length} AS jsonb)`;
      args.conditions.push(tag === "trash" ? trashCondition(tagCondition) : tagCondition);
    }
  } else if (!args.includeTrash) {
    args.params.push(["trash"]);
    args.conditions.push(`NOT (${trashCondition(`${normalizedTagsSql} @> CAST($${args.params.length} AS jsonb)`)})`);
  }

  for (const tag of args.excludedTags ?? []) {
    args.params.push([tag]);
    args.conditions.push(`NOT (${normalizedTagsSql} @> CAST($${args.params.length} AS jsonb))`);
  }
}

/**
 * Video lists expose one canonical no-overlay row per original. Its designer
 * revisions and its original are actions on that row, never duplicate cards.
 * The explicit variant predicate selects the card; only designer tags stay
 * excluded here, because legacy no-overlay rows carry a "no-overlay" tag.
 */
export function excludedVideoVariantTags(
  _tagList: string[] | null,
  _designerMissing = false,
): string[] {
  return ["designer"];
}

/** Virtual video views. Removed view names (#44) fall back to All. */
export const VIDEO_VIEWS: ReadonlySet<string> = new Set(["all", "needs-designer", "designer", "pending", "trash"]);
export const REMOVED_VIDEO_VIEWS: ReadonlySet<string> = new Set(["pipeline-final", "no-overlay"]);

export { normalizedTagsSql, videoVariantSql };

/* ========================================================================== */
/* Legacy designer-link fallback (#44): remove after the data move.           */
/*                                                                            */
/* Before #44 the overlaid video (variant pipeline-final, usually ID          */
/* `<source_id>`) was the canonical card. Old designer revisions point at it  */
/* (designer_of_id) or use the `<overlaid id>-designer` ID. Its row can hold  */
/* the active designer revision pointer, the approved title and the card      */
/* state (trash, pending, review). The data move (#47) moves these to the     */
/* no-overlay row. The rules are in the "Legacy overlaid contract" section of */
/* src/videoSql.ts; remove that section too. After the data move:            */
/*   - legacyOverlaidJoinSql: remove it and each `${legacyOverlaidJoinSql(...)}`*/
/*     call (GET /api/files rows and count, stream.ts, uploads.ts, publish, */
/*     PUT and DELETE in this file).                                          */
/*   - designerLinkSql      -> `${candidate}.designer_of_id = ${card}.id`     */
/*   - activeDesignerRevisionSql -> `${card}.active_designer_revision_id`     */
/*   - canonicalVideoTitleSql    -> `${card}.title`                           */
/*   - cardStateSql(legacy, column, expr) -> `expr`                           */
/*   - cardTrashConditionSql: remove it (addTagListConditions uses the tag).  */
/*   - writeThroughLegacyOverlaid: remove it and its calls.                  */
/* ========================================================================== */

/** Postgres client or transaction: the part that the helpers below use. */
type SqlRunner = Pick<ReturnType<typeof getDb>, "unsafe">;

/**
 * LEFT JOIN LATERAL that finds the primary legacy overlaid row of the
 * no-overlay card `card` one time, as the alias `legacy`. The row is NULL
 * when `card` is not a no-overlay video or has no legacy overlaid row.
 * The lateral gives only these columns, so it adds no ambiguous `project`,
 * `type` or `tags` column to a query: id, title, active_designer_revision_id,
 * visibility, publication_status, review_status (effective values).
 */
export function legacyOverlaidJoinSql(ident: string, card: string, legacy = "legacy"): string {
  const row = `${legacy}_row`;
  return `LEFT JOIN LATERAL (
       SELECT ${row}.id, ${row}.title, ${row}.active_designer_revision_id,
              ${visibilitySql(row)} AS visibility,
              ${publicationStatusSql(row)} AS publication_status,
              COALESCE(${row}.review_status, CASE WHEN ${normalizedTagsSql(row)} @> '["ready"]'::jsonb THEN 'approved' END) AS review_status
         FROM ${ident}.files AS ${row}
        WHERE ${card}.type = 'video' AND ${videoVariantSql(card)} = 'no-overlay'
          AND ${legacyOverlaidMatchSql(card, row)}
        ORDER BY ${legacyOverlaidOrderSql(row)}
        LIMIT 1
     ) AS ${legacy} ON TRUE`;
}

/**
 * State rule: while a legacy overlaid row exists, the card state comes from
 * it. `column` is visibility, publication_status or review_status, and
 * `cardExpr` is the effective value of the card row itself.
 */
export function cardStateSql(legacy: string, column: "visibility" | "publication_status" | "review_status", cardExpr: string): string {
  return `(CASE WHEN ${legacy}.id IS NOT NULL THEN ${legacy}.${column} ELSE ${cardExpr} END)`;
}

/** Trash condition for addTagListConditions: the legacy row wins over the card tag. */
export function cardTrashConditionSql(legacy: string): (tagCondition: string) => string {
  return (tagCondition) => `(CASE WHEN ${legacy}.id IS NOT NULL THEN ${legacy}.visibility = 'trash' ELSE ${tagCondition} END)`;
}

/**
 * True when the candidate row is a designer revision of the card. The match
 * includes the revisions of each legacy overlaid row, not only the primary
 * row, because the data move relinks all of them. The probes start from the
 * candidate ID columns, so each probe can use the primary key.
 */
export function designerLinkSql(ident: string, card: string, candidate: string): string {
  return `(${candidate}.designer_of_id = ${card}.id
    OR EXISTS (SELECT 1 FROM ${ident}.files AS legacy_link
      WHERE (legacy_link.id = ${candidate}.designer_of_id
          OR (${candidate}.id LIKE '%-designer' AND legacy_link.id = left(${candidate}.id, -length('-designer'))))
        AND ${legacyOverlaidMatchSql(card, "legacy_link")}))`;
}

/**
 * The active designer revision ID. The card's own pointer wins, then the
 * pointer of the primary legacy overlaid row. When both are NULL, the list
 * uses the newest linked revision.
 */
export function activeDesignerRevisionSql(card: string, legacy: string): string {
  return `COALESCE(${card}.active_designer_revision_id, ${legacy}.active_designer_revision_id)`;
}

/**
 * Title rule: the approved title of a video card. The card title wins. The
 * legacy overlaid title is used only when the card title is blank or has the
 * old " (No Overlay)" suffix, and the legacy title is not blank.
 */
export function canonicalVideoTitleSql(card: string, legacy: string): string {
  return `(CASE WHEN ${legacy}.id IS NOT NULL AND ${cardTitleNeedsLegacySql(card)}
      AND COALESCE(BTRIM(${legacy}.title), '') <> '' THEN BTRIM(${legacy}.title) ELSE ${card}.title END)`;
}

/**
 * Write-through: a write that changes the state or the title of a no-overlay
 * card also changes all of its legacy overlaid rows, in the same
 * transaction. Then the state rule above reads the new value. Only the
 * fields in `change` are written. Of the tags, only `trash` is changed.
 * Returns the number of legacy rows that changed.
 */
export async function writeThroughLegacyOverlaid(
  tx: SqlRunner,
  ident: string,
  project: string,
  cardId: string,
  change: { trash?: boolean; publicationStatus?: "pending" | "published"; title?: string | null },
): Promise<number> {
  const params: (string | boolean | null)[] = [cardId, project];
  const sets: string[] = [];
  if (change.trash !== undefined) {
    params.push(change.trash);
    const ref = `$${params.length}::boolean`;
    sets.push(`tags = (${normalizedTagsSql("legacy")} - 'trash') || CASE WHEN ${ref} THEN '["trash"]'::jsonb ELSE '[]'::jsonb END`);
    sets.push(`visibility = CASE WHEN ${ref} THEN 'trash' ELSE 'active' END`);
  }
  if (change.publicationStatus !== undefined) {
    params.push(change.publicationStatus);
    sets.push(`publication_status = $${params.length}`);
  }
  if (change.title !== undefined) {
    params.push(change.title);
    sets.push(`title = $${params.length}`);
  }
  if (sets.length === 0) return 0;
  const rows = await tx.unsafe<{ id: string }[]>(
    `UPDATE ${ident}.files AS legacy
        SET ${sets.join(", ")}
       FROM ${ident}.files AS card
      WHERE card.id = $1 AND card.project = $2 AND card.type = 'video'
        AND ${videoVariantSql("card")} = 'no-overlay'
        AND ${legacyOverlaidMatchSql("card", "legacy")}
      RETURNING legacy.id`,
    params,
  );
  return rows.length;
}

/* ===================== End of legacy designer-link fallback ================ */

/* -------------------------------------------------------------------------- */
/* GET /api/files                                                             */
/* -------------------------------------------------------------------------- */

filesRouter.get("/projects/:token/:project/api/files", async (c) => {
  const { token, project } = c.req.param();
  await verifyMediaToken(token);

  const url = new URL(c.req.url);
  const typeParam = url.searchParams.get("type") as FileType | null;
  const tagsParam = url.searchParams.get("tags") ?? undefined;
  const requestedView = url.searchParams.get("view") ?? undefined;
  const sort = url.searchParams.get("sort") ?? "asc";
  const limitParam = url.searchParams.get("limit");
  const offsetParam = url.searchParams.get("offset");
  const checkId = url.searchParams.get("check_id");
  const checkTitle = url.searchParams.get("check_title");
  const includeTrashParam = url.searchParams.get("include_trash") === "true";
  const includePending = url.searchParams.get("include_pending") === "true";
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
  } else {
    // Old subtitle rows stay in the database until the data move (#44).
    conditions.push("type IN ('audio', 'video', 'original')");
  }

  // The no-overlay video is the canonical card. A designer revision is a
  // linked presentation of that card, not a list item in its own right.
  // Legacy designer rows use the `-designer` suffix and no designer_of_id.
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
        AND ${designerLinkSql(ident, "source", "designer_candidate")}
        AND NOT (${normalizedTagsSql("designer_candidate")} @> '["trash"]'::jsonb)
    )`);
  }

  // Virtual views are relationship/state queries. They never create a second
  // card for a derived object and do not depend on folder or publisher tags.
  // The card state uses the legacy overlaid row while it exists.
  const visibilityExpr = cardStateSql("legacy", "visibility", visibilitySql("source"));
  const publicationExpr = cardStateSql("legacy", "publication_status", `COALESCE(source.publication_status, CASE WHEN ${normalizedTagsSql("source")} @> '["pending"]'::jsonb THEN 'pending' WHEN source.type='video' THEN 'published' ELSE NULL END)`);
  const reviewExpr = cardStateSql("legacy", "review_status", `COALESCE(source.review_status, CASE WHEN ${normalizedTagsSql("source")} @> '["ready"]'::jsonb THEN 'approved' WHEN source.type='audio' THEN 'todo' ELSE NULL END)`);
  if (view === "trash") conditions.push(`${visibilityExpr} = 'trash'`);
  if (view === "pending") conditions.push(`${publicationExpr} = 'pending'`);
  if (view === "todo") conditions.push(`COALESCE(${reviewExpr}, 'todo') = 'todo'`);
  if (view === "approved") conditions.push(`COALESCE(${reviewExpr}, 'todo') = 'approved'`);
  if (view === "needs-designer") conditions.push(`NOT EXISTS (
    SELECT 1 FROM ${ident}.files candidate WHERE candidate.project=source.project
      AND candidate.type='video' AND ${designerLinkSql(ident, "source", "candidate")}
      AND COALESCE(candidate.visibility, CASE WHEN ${normalizedTagsSql("candidate")} @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END) <> 'trash'
  )`);
  if (view === "designer") conditions.push(`EXISTS (
    SELECT 1 FROM ${ident}.files candidate WHERE candidate.project=source.project
      AND candidate.type='video' AND ${designerLinkSql(ident, "source", "candidate")}
  )`);

  addTagListConditions({
    conditions,
    params,
    tagList,
    includeTrash,
    includePending,
    excludedTags: typeParam === "video" ? excludedVideoVariantTags(tagList, designerMissing) : [],
    ...(typeParam === "video" ? { trashCondition: cardTrashConditionSql("legacy") } : {}),
  });
  const legacyJoin = legacyOverlaidJoinSql(ident, "source");

  const whereClause = conditions.join(" AND ");
  const sortDirection = sort === "asc" ? "ASC" : "DESC";

  let pageClause = "";
  if (pageSize !== null) {
    // Fetch one extra row so callers can know whether to request another page
    // without transferring or rendering the full virtual view.
    params.push(pageSize + 1);
    const limitPosition = params.length;
    params.push(pageOffset);
    const offsetPosition = params.length;
    pageClause = ` LIMIT $${limitPosition} OFFSET $${offsetPosition}`;
  }

  const rowsPromise = sql.unsafe<FileRow[]>(
    `SELECT source.id, source.project, source.type, ${typeParam === "video" ? canonicalVideoTitleSql("source", "legacy") : "source.title"} AS title, source.tags, source.duration, source.file_size, source.mime_type, source.created_at, source.source_id, source.original_filename, source.checksum_sha256, derived.title AS derived_title, designer.id AS designer_video_id, active_designer.id AS active_designer_revision_id, source.designer_of_id,
       ${videoVariantSql("source")} AS media_variant,
       ${reviewExpr} AS review_status,
       ${visibilityExpr} AS visibility,
       ${publicationExpr} AS publication_status,
       review.id AS review_audio_id
     FROM ${ident}.files AS source
     ${legacyJoin}
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
       SELECT CASE WHEN source.type = 'video' THEN ${activeDesignerRevisionSql("source", "legacy")} END AS id
     ) AS active_designer ON TRUE
     LEFT JOIN LATERAL (
       SELECT candidate.id
       FROM ${ident}.files AS candidate
       WHERE source.type = 'video'
         AND candidate.project = source.project
         AND candidate.type = 'video'
         AND (candidate.id = active_designer.id OR (active_designer.id IS NULL AND ${designerLinkSql(ident, "source", "candidate")}))
         AND NOT (${normalizedTagsSql("candidate")} @> '["trash"]'::jsonb)
       ORDER BY candidate.created_at DESC, candidate.id
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
      `SELECT COUNT(*)::text AS total FROM ${ident}.files AS source ${legacyJoin} WHERE ${whereClause}`,
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
  return c.json(visibleRows.map(rowToResponse), 200, headers);
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
    SET tags = '["ready"]'::jsonb, review_status = 'approved', visibility = COALESCE(visibility, 'active')
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
  if (typeRaw !== "audio" && typeRaw !== "video" && typeRaw !== "original") {
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
  } else if (rowType === "video") {
    tags = validateVideoTags(tags);
  }
  if (tags.length === 0 && rowType === "audio") {
    tags = ["todo"];
  }

  await sql.begin(async (tx) => {
    if (title !== undefined) {
      await tx.unsafe(
        `UPDATE ${ident}.files
           SET tags = $1::jsonb, title = $2,
               visibility = CASE WHEN $1::jsonb @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END,
               review_status = CASE WHEN $5 = 'audio' THEN CASE WHEN $1::jsonb @> '["ready"]'::jsonb THEN 'approved' ELSE 'todo' END ELSE review_status END
           WHERE id = $3 AND project = $4 AND type = $5`,
        [JSON.stringify(tags), title, id, project, rowType],
      );
    } else {
      await tx.unsafe(
        `UPDATE ${ident}.files
           SET tags = $1::jsonb,
               visibility = CASE WHEN $1::jsonb @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END,
               review_status = CASE WHEN $4 = 'audio' THEN CASE WHEN $1::jsonb @> '["ready"]'::jsonb THEN 'approved' ELSE 'todo' END ELSE review_status END
           WHERE id = $2 AND project = $3 AND type = $4`,
        [JSON.stringify(tags), id, project, rowType],
      );
    }
    if (rowType === "video") {
      await writeThroughLegacyOverlaid(tx, ident, project, id, {
        trash: tags.includes("trash"),
        ...(title !== undefined ? { title } : {}),
      });
    }
  });

  return c.json({
    ok: true,
    id,
    tags,
    title: title ?? null,
  });
});

filesRouter.post("/projects/:token/:project/api/files/:id/publish", async (c) => {
  const { token, project, id: idRaw } = c.req.param();
  await verifyMediaToken(token);
  const id = sanitizeFileId(idRaw);
  if (!id) throw new HttpError(400, "Invalid file ID");
  const sql = getDb();
  const ident = schemaIdent();
  // The card must be active. While a legacy overlaid row exists, it holds
  // the card state.
  const published = await sql.begin(async (tx) => {
    const rows = await tx.unsafe<{ id: string }[]>(
      `UPDATE ${ident}.files AS card
          SET publication_status='published'
        WHERE card.id=$1 AND card.project=$2 AND card.type='video'
          AND (SELECT ${cardStateSql("legacy", "visibility", visibilitySql("card"))}
                 FROM (SELECT 1) AS one ${legacyOverlaidJoinSql(ident, "card")}) = 'active'
        RETURNING card.id`,
      [id, project],
    );
    if (!rows[0]) return false;
    await writeThroughLegacyOverlaid(tx, ident, project, id, { publicationStatus: "published" });
    return true;
  });
  if (!published) throw new HttpError(404, "Active video not found");
  return c.json({ ok: true, id, publication_status: "published" });
});

/* -------------------------------------------------------------------------- */
/* DELETE /api/files/:id                                                      */
/* -------------------------------------------------------------------------- */

filesRouter.delete("/projects/:token/:project/api/files/:id", async (c) => {
  const { token, project, id: idRaw } = c.req.param();
  await verifyMediaToken(token);

  const url = new URL(c.req.url);
  const typeRaw = url.searchParams.get("type");
  if (typeRaw !== "audio" && typeRaw !== "video" && typeRaw !== "original") {
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
    legacy_visibility: string | null;
  }[]>(
    `SELECT file.type, file.tags, file.mime_type, legacy.visibility AS legacy_visibility
       FROM ${ident}.files AS file
       ${legacyOverlaidJoinSql(ident, "file")}
       WHERE file.id = $1 AND file.project = $2 AND file.type = $3`,
    [id, project, fileType],
  );
  if (rows.length === 0) {
    throw new HttpError(404, `File '${id}' of type '${fileType}' not found`);
  }
  const row = rows[0]!;
  const tags = parseTagsValue(row.tags);
  // While a legacy overlaid row exists, it holds the card state.
  const trashed = row.legacy_visibility !== null ? row.legacy_visibility === "trash" : tags.includes("trash");
  if (!trashed) {
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

  // Removing an original invalidates any in-flight source-processing work for
  // that source. Keep this transition with the metadata delete so a worker
  // cannot later resume a waiting job after its source has disappeared.
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

  return c.json({ ok: true, id, deleted: true });
});
