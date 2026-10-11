/**
 * Startup and shutdown steps of the Media Manager service.
 *
 * server.ts calls runStartup() before it opens the HTTP port. The steps and
 * their order are the same as in the old Bun service file index.ts:
 *   1. load the configuration (throws on a missing required variable),
 *   2. make sure that the Postgres schema is ready,
 *   3. re-queue interrupted originals (before step 5, because the re-queue
 *      reads the active upload sessions that step 5 aborts),
 *   4. check the S3 bucket (HeadBucket),
 *   5. clean up expired upload sessions.
 */

import { type AppConfig, loadConfig } from "./config.ts";
import { closeDb, ensureDatabaseReady } from "./db.ts";
import { reconcileSourceProcessing } from "./sourceProcessing.ts";
import { ensureStorageBackendReady } from "./storage.ts";
import { cleanupExpiredUploadSessions } from "./uploads.ts";

export async function runStartup(): Promise<AppConfig> {
  const config = loadConfig();
  console.log(
    `[startup] media-manager checking Postgres schema "${config.dbSchema}" and S3 bucket "${config.s3Bucket}" ...`,
  );
  await ensureDatabaseReady();
  const recoveredProcessingJobs = await reconcileSourceProcessing();
  if (recoveredProcessingJobs > 0) console.log(`[startup] recovered ${recoveredProcessingJobs} source-processing job(s)`);
  await ensureStorageBackendReady();
  await cleanupExpiredUploadSessions();
  return config;
}

/** Release the shared resources (the Postgres pool waits at most 5 s). */
export async function releaseResources(): Promise<void> {
  await closeDb().catch(() => {});
}
