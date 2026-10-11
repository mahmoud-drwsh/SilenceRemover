/**
 * Source-processing data helpers. #62 adds the worker routes and uses this
 * module. The startup re-queue and the upload enqueue (#60) are the same as
 * in remote-js/src/routes/sourceProcessing.ts.
 */

import { randomUUID } from "node:crypto";
import { isSourceProcessingEnabled, loadConfig } from "./config.ts";
import { getDb, schemaIdent } from "./db.ts";

/**
 * Queue a source-processing job for each original whose upload session is
 * still active (the service stopped between the metadata insert and the
 * session completion). Returns the number of new jobs.
 */
export async function reconcileSourceProcessing(): Promise<number> {
  const sql = getDb(); const ident = schemaIdent(); const profile = loadConfig().sourceProcessingProfile;
  const rows = await sql.unsafe<{ count: string }[]>(`
    WITH queued AS (
      INSERT INTO ${ident}.source_processing
        (id,project,source_id,original_checksum_sha256,processing_profile)
      SELECT md5(random()::text || clock_timestamp()::text || f.id),f.project,f.id,f.checksum_sha256,$1
      FROM ${ident}.files f
      JOIN ${ident}.upload_sessions u ON u.project=f.project AND u.file_id=f.id
        AND u.type='original' AND u.checksum_sha256=f.checksum_sha256 AND u.state='active'
      WHERE f.type='original' AND f.checksum_sha256 IS NOT NULL
      ON CONFLICT (project,source_id,original_checksum_sha256,processing_profile) DO NOTHING
      RETURNING 1
    ) SELECT count(*)::text count FROM queued`, [profile]);
  return Number(rows[0]?.count ?? 0);
}

/**
 * Queue source processing for one committed original. The insert does
 * nothing when the job for this checksum and profile exists. Returns true
 * when a new job was added.
 */
export async function enqueueSourceProcessing(
  project: string, sourceId: string, originalChecksumSha256: string,
): Promise<boolean> {
  if (!isSourceProcessingEnabled(project)) return false;
  const sql = getDb(); const ident = schemaIdent(); const profile = loadConfig().sourceProcessingProfile;
  const rows = await sql.unsafe<{ id: string }[]>(`
    INSERT INTO ${ident}.source_processing
      (id,project,source_id,original_checksum_sha256,processing_profile)
    VALUES ($1,$2,$3,$4,$5)
    ON CONFLICT (project,source_id,original_checksum_sha256,processing_profile) DO NOTHING
    RETURNING id`, [randomUUID(), project, sourceId, originalChecksumSha256, profile]);
  return Boolean(rows[0]);
}
