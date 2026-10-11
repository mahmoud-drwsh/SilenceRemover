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

/** One `source_processing` row, as the routes return it. */
export interface SourceProcessingJob {
  id: string;
  project: string;
  source_id: string;
  original_checksum_sha256: string;
  processing_profile: string;
  state: string;
  attempts: number;
  lease_token: string | null;
  lease_until: string | Date | null;
  trim_plan: unknown;
  review_transcript: string | null;
  generated_title: string | null;
  waiting_reason: string | null;
  last_error: string | null;
}

function jsonObject(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : value;
  } catch {
    return value;
  }
}

/**
 * `SELECT *` can still return the old `srt_text` column until the data move
 * drops it. The response never includes it. A trim plan stored as JSON text
 * is returned as an object. Same as serializeJob in
 * remote-js/src/routes/sourceProcessing.ts; #62 can use it too.
 */
export function serializeSourceProcessingJob(row: SourceProcessingJob): SourceProcessingJob {
  const { srt_text: _removed, ...job } = row as SourceProcessingJob & { srt_text?: unknown };
  return { ...job, trim_plan: jsonObject(job.trim_plan) };
}
