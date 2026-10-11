/**
 * Upload-session data helpers. #60 adds the upload routes and uses this
 * module. The startup cleanup is the same as in remote-js/src/routes/uploads.ts.
 */

import { getDb, schemaIdent } from "./db.ts";
import { getExtensionForMime } from "./mime.ts";
import type { FileType } from "./schemas.ts";
import { abortMultipartUpload } from "./storage.ts";

export type UploadSession = {
  id: string; project: string; file_id: string; type: FileType; mime_type: string;
  file_size: number; checksum_sha256: string; title: string; tags: unknown;
  source_id: string | null; original_filename: string | null; upload_id: string | null;
  designer_of_id: string | null;
  media_variant: "pipeline-final" | "no-overlay" | "designer" | null;
  visibility: "active" | "trash" | null;
  publication_status: "pending" | "published" | null;
  expires_at: string | Date; state: "active" | "completed" | "aborted";
};

/** Abort the S3 multipart upload of each expired active session and mark it aborted. */
export async function cleanupExpiredUploadSessions(): Promise<void> {
  const sql = getDb(); const ident = schemaIdent();
  const sessions = await sql.unsafe<UploadSession[]>(`SELECT * FROM ${ident}.upload_sessions WHERE state='active' AND expires_at < now()`);
  for (const session of sessions) {
    if (session.upload_id) await abortMultipartUpload(session.type, session.project, session.file_id, getExtensionForMime(session.mime_type), session.upload_id).catch(() => {});
    await sql.unsafe(`UPDATE ${ident}.upload_sessions SET state='aborted' WHERE id=$1`, [session.id]);
  }
}
