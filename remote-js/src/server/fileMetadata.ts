/**
 * File-row helpers for the upload routes (#60). These are the same helpers
 * as in remote-js/src/routes/files.ts, with the same export names, so that
 * the file routes (#57, #59) can use them too.
 */

import { getDb, schemaIdent } from "./db.ts";
import { HttpError, type FileType, validateAudioTags, validateVideoTags } from "./schemas.ts";
import { normalizeTitle } from "./sanitize.ts";

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

/** The tags of a row. Legacy rows keep the array as a JSON string. */
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

  let tags = (parsed as unknown[]).map(String);
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
