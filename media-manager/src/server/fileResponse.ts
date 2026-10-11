/**
 * The FileResponse shape of the file API (read side). Ported without change
 * from remote-js/src/routes/files.ts: the row type and the row-to-response
 * mapping. The tag parsing and the legacy tag-to-attribute bridge are in
 * fileMetadata.ts (#60).
 */

import type { FileResponse, FileType } from "./schemas.ts";
import { legacyMediaAttributes, parseTagsValue } from "./fileMetadata.ts";

export interface FileRow {
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
  review_audio_id?: string | null;
}

function serializeCreatedAt(value: Date | string | null): string {
  if (!value) return "";
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

export function rowToResponse(row: FileRow): FileResponse {
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
