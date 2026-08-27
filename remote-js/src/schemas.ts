/**
 * Zod schemas mirroring the Pydantic models in remote/app.py.
 *
 * The shapes match exactly so the existing pipeline client and SPA can talk
 * to this service without changes.
 */

import { z } from "zod";

export const FileTypeSchema = z.enum(["audio", "video", "original", "subtitle"]);
export type FileType = z.infer<typeof FileTypeSchema>;

export const FileResponseSchema = z.object({
  id: z.string(),
  project: z.string(),
  type: FileTypeSchema,
  title: z.string().nullable(),
  tags: z.array(z.string()),
  duration: z.number().int(),
  file_size: z.number().int(),
  mime_type: z.string(),
  source_id: z.string().nullable().optional(),
  original_filename: z.string().nullable().optional(),
  checksum_sha256: z.string().nullable().optional(),
  derived_title: z.string().nullable().optional(),
  no_overlay_id: z.string().nullable().optional(),
  designer_video_id: z.string().nullable().optional(),
  subtitle_id: z.string().nullable().optional(),
  designer_of_id: z.string().nullable().optional(),
  media_variant: z.enum(["pipeline-final", "no-overlay", "designer"]).nullable().optional(),
  review_status: z.enum(["todo", "approved"]).nullable().optional(),
  visibility: z.enum(["active", "trash"]).optional(),
  publication_status: z.enum(["pending", "published"]).nullable().optional(),
  review_audio_id: z.string().nullable().optional(),
  created_at: z.string(),
});
export type FileResponse = z.infer<typeof FileResponseSchema>;

export const UpdateFileRequestSchema = z.object({
  tags: z.array(z.string()),
  title: z.string().nullable().optional(),
});
export type UpdateFileRequest = z.infer<typeof UpdateFileRequestSchema>;

export const UploadResponseSchema = z.object({
  ok: z.boolean(),
  id: z.string(),
  type: z.string(),
  overwritten: z.boolean().default(false),
});
export type UploadResponse = z.infer<typeof UploadResponseSchema>;

export const SetMediaTokenRequestSchema = z.object({
  token: z.string().min(1),
});
export type SetMediaTokenRequest = z.infer<typeof SetMediaTokenRequestSchema>;

/** Audio tags are restricted to a fixed set; mirrors `AUDIO_TAGS`. */
export const AUDIO_TAGS: ReadonlySet<string> = new Set([
  "todo",
  "ready",
  "trash",
]);

/** Throw if any of the supplied tags is not in the audio tag set. */
export function validateAudioTags(tags: string[]): string[] {
  const invalid = tags.filter((t) => !AUDIO_TAGS.has(t));
  if (invalid.length > 0) {
    const allowed = [...AUDIO_TAGS].join(", ");
    throw new HttpError(400, `Invalid audio tags: ${JSON.stringify(invalid)}. Allowed: {${allowed}}`);
  }
  return tags;
}

/** Lightweight HTTP error usable from any route. Captures the status code. */
export class HttpError extends Error {
  status: number;
  headers?: Record<string, string>;
  constructor(status: number, message: string, headers?: Record<string, string>) {
    super(message);
    this.status = status;
    if (headers) this.headers = headers;
  }
}
