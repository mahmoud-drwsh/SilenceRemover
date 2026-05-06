import { parseTagsJson } from "./tags";

export type FileRow = {
  id: string;
  project: string;
  type: string;
  title: string | null;
  tags: unknown;
  duration: number;
  file_size: number;
  mime_type: string;
  created_at: Date | string;
};

export function toFileResponse(row: FileRow) {
  const created =
    row.created_at instanceof Date
      ? row.created_at.toISOString()
      : String(row.created_at);
  return {
    id: row.id,
    project: row.project,
    type: row.type,
    title: row.title,
    tags: parseTagsJson(row.tags),
    duration: Number(row.duration),
    file_size: Number(row.file_size),
    mime_type: row.mime_type,
    created_at: created,
  };
}
