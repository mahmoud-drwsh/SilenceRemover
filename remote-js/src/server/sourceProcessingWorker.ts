/**
 * Worker routes of the durable source-processing queue (spec #55, ticket #62).
 * Same contract as the old Bun service file routes/sourceProcessing.ts: the same SQL,
 * status codes, error texts, and response shapes. Each function serves one
 * route; the route files in app/internal/source-processing/ only read the
 * path parameters and call it.
 *
 * Every route checks the X-Source-Processing-Token header first. Each call
 * except claim and prerender-candidate checks the lease token.
 */

import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import type postgres from "postgres";
import { isSourceProcessingEnabled, loadConfig } from "./config.ts";
import { getDb, schemaIdent } from "./db.ts";
import { getExtensionForMime } from "./mime.ts";
import { HttpError } from "./schemas.ts";
import { serializeSourceProcessingJob, type SourceProcessingJob } from "./sourceProcessing.ts";
import {
  deleteSourceArtifactTemporary,
  presignOriginalDownload,
  presignSourceArtifactPut,
  promoteSourceArtifact,
  sourceArtifactTemporaryHead,
  sourceArtifactTemporarySha256,
} from "./storage.ts";

type Body = Record<string, unknown>;
type Result = Record<string, unknown>;

interface OriginalForWorker {
  mime_type: string;
  original_filename: string | null;
}

interface ArtifactIdentity {
  type: "audio" | "video";
  id: string;
  mime: string;
  ext: string;
  tags: string[];
  mediaVariant: string | null;
  reviewStatus: string | null;
  publicationStatus: string | null;
}

const SHA256 = /^[a-f0-9]{64}$/;
const LEASE_NOT_ACTIVE = "Source-processing job lease is not active";

/** The test that the job's original exists with the queued checksum. */
function originalExists(ident: string): string {
  return `EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
        AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)`;
}

/** The test that an audio row is approved (tag ready) and not in the trash. */
function approvedAudio(alias: string): string {
  const tags = `(CASE WHEN jsonb_typeof(${alias}.tags)='string' THEN (${alias}.tags #>> '{}')::jsonb ELSE ${alias}.tags END)`;
  return `${tags} @> '["ready"]'::jsonb AND NOT (${tags} @> '["trash"]'::jsonb)`;
}

function workerTokenDigest(value: string): Buffer {
  return createHash("sha256").update(value).digest();
}

/**
 * Compare the worker header with the configured token in constant time.
 * When the token is not configured, every worker call gives 401.
 */
export function verifySourceProcessingWorkerToken(header: string | null | undefined): void {
  const expected = loadConfig().sourceProcessingWorkerToken;
  if (!header || !expected || !timingSafeEqual(workerTokenDigest(header), workerTokenDigest(expected))) {
    throw new HttpError(401, "Invalid source-processing worker token");
  }
}

/** Check the worker header of a request. */
function authorize(request: Request): void {
  verifySourceProcessingWorkerToken(request.headers.get("X-Source-Processing-Token"));
}

/** The JSON body. A body that is not JSON becomes `{}`, as in the old service. */
async function readBody(request: Request): Promise<Body> {
  return await request.json().catch(() => ({})) as Body;
}

function leaseToken(body: Body): string {
  const value = String(body.lease_token ?? "");
  if (!value) throw new HttpError(409, LEASE_NOT_ACTIVE);
  return value;
}

function optionalString(body: Body, key: string, limit: number): string | undefined {
  if (!(key in body)) return undefined;
  const value = body[key];
  if (typeof value !== "string" || value.length > limit) {
    throw new HttpError(400, `${key} must be a string no longer than ${limit} characters`);
  }
  return value;
}

/** JSON kept with a job is bounded control-plane metadata, never media bytes. */
function optionalTrimPlan(body: Body): string | undefined {
  if (!("trim_plan" in body)) return undefined;
  const value = body.trim_plan;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(400, "trim_plan must be an object");
  }
  const encoded = JSON.stringify(value);
  if (encoded.length > 64 * 1024) throw new HttpError(400, "trim_plan is too large");
  return encoded;
}

/**
 * The worker uploads only two artifact kinds: the review audio and the
 * no-overlay video (#44). Other kinds get 400.
 */
function artifactIdentity(kind: unknown, sourceId: string): ArtifactIdentity {
  if (kind === "review_audio") return { type: "audio", id: sourceId, mime: "audio/ogg", ext: ".ogg", tags: ["todo"], mediaVariant: null, reviewStatus: "todo", publicationStatus: null };
  if (kind === "no_overlay_video") return { type: "video", id: `${sourceId}-no-overlay`, mime: "video/mp4", ext: ".mp4", tags: [], mediaVariant: "no-overlay", reviewStatus: null, publicationStatus: "published" };
  throw new HttpError(400, "Unsupported source-processing artifact kind");
}

/** The approved title of the review audio. The review queue owns the final title. */
async function approvedAudioTitle(
  sql: Pick<postgres.Sql, "unsafe">, ident: string, project: string, sourceId: string,
): Promise<string | null> {
  const rows = await sql.unsafe<{ title: string | null }[]>(`
    SELECT title FROM ${ident}.files a
    WHERE a.project=$1 AND a.id=$2 AND a.type='audio' AND ${approvedAudio("a")}
    LIMIT 1`, [project, sourceId]);
  return rows[0]?.title?.trim() || null;
}

/** The size and SHA-256 that the worker sends with an artifact. */
function artifactSizeAndChecksum(body: Body): { size: number; checksum: string } {
  const size = Number(body.size);
  const checksum = String(body.checksum_sha256 ?? "").toLowerCase();
  if (!Number.isSafeInteger(size) || size <= 0 || !SHA256.test(checksum)) {
    throw new HttpError(400, "Valid size and checksum_sha256 are required");
  }
  return { size, checksum };
}

/**
 * After a lease-checked update found no row: when the lease is valid but the
 * original changed, mark the job stale and give that 409. Else the lease is
 * not active.
 */
async function leaseMiss(project: string, jobId: string, token: string): Promise<never> {
  const sql = getDb(); const ident = schemaIdent();
  const stale = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing j SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3 AND j.lease_until > now()
      AND NOT ${originalExists(ident)}
    RETURNING id`, [project, jobId, token]);
  if (stale[0]) throw new HttpError(409, "Original changed after source processing was queued");
  throw new HttpError(409, LEASE_NOT_ACTIVE);
}

/** POST /internal/source-processing/:project/claim */
export async function claimJob(request: Request, project: string): Promise<Result> {
  authorize(request);
  if (!isSourceProcessingEnabled(project)) return { ok: true, job: null };
  const sql = getDb(); const ident = schemaIdent(); const token = randomUUID();
  const leaseSeconds = loadConfig().sourceProcessingLeaseSeconds;
  // A job whose original is gone can stay invisible to the claim forever
  // (a waiting job has no review audio to make it claimable). Mark it stale.
  await sql.unsafe(`
    UPDATE ${ident}.source_processing j
       SET state='stale', lease_token=NULL, lease_until=NULL,
           waiting_reason=NULL, last_error='original missing', updated_at=now()
     WHERE j.project=$1 AND j.state IN ('pending', 'claimed', 'waiting')
       AND NOT ${originalExists(ident)}`, [project]);
  await sql.unsafe(`
    UPDATE ${ident}.source_processing SET state='failed',lease_token=NULL,lease_until=NULL,
      last_error='worker lease expired after maximum attempts',updated_at=now()
    WHERE project=$1 AND state='claimed' AND attempts >= 5 AND lease_until < now()`, [project]);
  const rows = await sql.unsafe<SourceProcessingJob[]>(`
    WITH candidate AS (
      SELECT id FROM ${ident}.source_processing
      WHERE project=$1 AND attempts < 5
        AND (
          state='pending'
          OR (state='claimed' AND lease_until < now())
          OR (
            state='waiting' AND waiting_reason='waiting for title review'
            AND EXISTS (
              SELECT 1 FROM ${ident}.files a
              WHERE a.project=source_processing.project AND a.id=source_processing.source_id
                AND a.type='audio' AND ${approvedAudio("a")}
            )
          )
        )
      ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE ${ident}.source_processing j
    SET state='claimed',attempts=attempts+1,lease_token=$2,
        lease_until=now()+($3 * interval '1 second'),last_error=NULL,updated_at=now()
    FROM candidate WHERE j.id=candidate.id RETURNING j.*`, [project, token, leaseSeconds]);
  const job = rows[0];
  if (!job) return { ok: true, job: null };
  const original = (await sql.unsafe<OriginalForWorker[]>(`
    SELECT mime_type,original_filename FROM ${ident}.files
    WHERE project=$1 AND id=$2 AND type='original' AND checksum_sha256=$3`,
    [project, job.source_id, job.original_checksum_sha256]))[0];
  if (!original) {
    await sql.unsafe(`UPDATE ${ident}.source_processing SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=$1`, [job.id]);
    return { ok: true, job: null };
  }
  const ext = getExtensionForMime(original.mime_type);
  const filename = original.original_filename ?? `${job.source_id}${ext}`;
  const downloadUrl = await presignOriginalDownload(project, job.source_id, ext, filename);
  const reviewAudio = await sql.unsafe<{ id: string }[]>(
    `SELECT id FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='audio'`, [project, job.source_id]);
  const noOverlay = await sql.unsafe<{ id: string }[]>(
    `SELECT id FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='video'`, [project, `${job.source_id}-no-overlay`]);
  // The raw approved title (not trimmed), as in the old claim response.
  const approved = await sql.unsafe<{ title: string | null }[]>(`
    SELECT title FROM ${ident}.files a
    WHERE a.project=$1 AND a.id=$2 AND a.type='audio' AND ${approvedAudio("a")}
    LIMIT 1`, [project, job.source_id]);
  return { ok: true, job: {
    ...serializeSourceProcessingJob(job),
    lease_token: token,
    original_download_url: downloadUrl,
    original_filename: filename,
    review_audio_uploaded: Boolean(reviewAudio[0]),
    no_overlay_uploaded: Boolean(noOverlay[0]),
    approved_title: approved[0]?.title ?? null,
  } };
}

/**
 * POST /internal/source-processing/:project/prerender-candidate
 * An idle worker pre-encodes title-independent media for a job that waits
 * for title review. This needs no lease: the worker uploads nothing until it
 * claims the job again after approval. `exclude` lists the jobs that the
 * worker already has.
 */
export async function prerenderCandidate(request: Request, project: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const exclude = (Array.isArray(body.exclude) ? body.exclude : [])
    .filter((value): value is string => typeof value === "string").slice(0, 5000);
  const sql = getDb(); const ident = schemaIdent();
  const job = (await sql.unsafe<(SourceProcessingJob & OriginalForWorker)[]>(`
    SELECT j.*, f.mime_type, f.original_filename FROM ${ident}.source_processing j
    JOIN ${ident}.files f ON f.project=j.project AND f.id=j.source_id
      AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256
    WHERE j.project=$1 AND j.state='waiting' AND j.waiting_reason='waiting for title review'
      AND j.trim_plan IS NOT NULL
      AND j.id NOT IN (SELECT jsonb_array_elements_text($2::text::jsonb))
    ORDER BY j.updated_at,j.id LIMIT 1`, [project, JSON.stringify(exclude)]))[0];
  if (!job) return { ok: true, job: null };
  const ext = getExtensionForMime(job.mime_type);
  const filename = job.original_filename ?? `${job.source_id}${ext}`;
  return { ok: true, job: {
    id: job.id,
    source_id: job.source_id,
    original_checksum_sha256: job.original_checksum_sha256,
    trim_plan: serializeSourceProcessingJob(job).trim_plan,
    original_download_url: await presignOriginalDownload(project, job.source_id, ext, filename),
    original_filename: filename,
  } };
}

/** POST /internal/source-processing/:project/:jobId/artifacts/initiate */
export async function initiateArtifact(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const token = leaseToken(body);
  const { checksum } = artifactSizeAndChecksum(body);
  const title = String(body.title ?? "");
  const sql = getDb(); const ident = schemaIdent();
  const row = (await sql.unsafe<SourceProcessingJob[]>(`
    SELECT * FROM ${ident}.source_processing j WHERE project=$1 AND id=$2 AND state='claimed'
      AND lease_token=$3 AND lease_until > now() AND ${originalExists(ident)}`, [project, jobId, token]))[0];
  if (!row) throw new HttpError(409, LEASE_NOT_ACTIVE);
  const artifact = artifactIdentity(body.kind, row.source_id);
  const existing = (await sql.unsafe<{ checksum_sha256: string | null }[]>(
    `SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`,
    [project, artifact.id, artifact.type]))[0];
  if (existing) {
    if (existing.checksum_sha256 === checksum) return { ok: true, already_uploaded: true, id: artifact.id };
    throw new HttpError(409, "A different artifact already exists for this source");
  }
  if (artifact.type === "audio" && (!row.generated_title || title !== row.generated_title)) {
    throw new HttpError(409, "Review audio title must match the checkpointed title");
  }
  if (artifact.type === "video") {
    const approved = await approvedAudioTitle(sql, ident, project, row.source_id);
    if (!approved || title !== approved) throw new HttpError(409, "Video title must match the approved review title");
  }
  return {
    ok: true, id: artifact.id,
    upload_url: await presignSourceArtifactPut(project, jobId, token, String(body.kind), artifact.mime),
  };
}

/**
 * POST /internal/source-processing/:project/:jobId/artifacts/complete
 * One transaction locks the job, checks the lease and the title, checks the
 * size and the SHA-256 of the temporary object, copies it to the final key,
 * and adds the file row.
 */
export async function completeArtifact(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const token = leaseToken(body);
  const { size, checksum } = artifactSizeAndChecksum(body);
  const duration = Number(body.duration ?? 0);
  if (!Number.isFinite(duration) || duration < 0 || duration > 24 * 60 * 60) {
    throw new HttpError(400, "duration must be a valid media duration");
  }
  const sql = getDb(); const ident = schemaIdent(); const kind = String(body.kind); const title = String(body.title ?? "");
  const completedId = await sql.begin(async (tx) => {
    const row = (await tx.unsafe<SourceProcessingJob[]>(`
      SELECT * FROM ${ident}.source_processing j WHERE project=$1 AND id=$2 AND state='claimed'
        AND lease_token=$3 AND lease_until > now() AND ${originalExists(ident)}
      FOR UPDATE`, [project, jobId, token]))[0];
    if (!row) throw new HttpError(409, LEASE_NOT_ACTIVE);
    const artifact = artifactIdentity(body.kind, row.source_id);
    if (artifact.type === "audio" && (!row.generated_title || title !== row.generated_title)) {
      throw new HttpError(409, "Review audio title must match the checkpointed title");
    }
    if (artifact.type === "video") {
      const approved = await approvedAudioTitle(tx, ident, project, row.source_id);
      if (!approved || title !== approved) throw new HttpError(409, "Video title must match the approved review title");
    }
    const existing = (await tx.unsafe<{ checksum_sha256: string | null }[]>(
      `SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`,
      [project, artifact.id, artifact.type]))[0];
    if (existing) {
      if (existing.checksum_sha256 === checksum) return artifact.id;
      throw new HttpError(409, "A different artifact already exists for this source");
    }
    const head = await sourceArtifactTemporaryHead(project, jobId, token, kind);
    if (!head || head.size !== size || await sourceArtifactTemporarySha256(project, jobId, token, kind) !== checksum) {
      throw new HttpError(400, "Uploaded artifact verification failed");
    }
    await promoteSourceArtifact(project, jobId, token, kind, artifact.type, artifact.id, artifact.ext, artifact.mime);
    await tx.unsafe(`
      INSERT INTO ${ident}.files (id,project,type,title,tags,duration,file_size,mime_type,source_id,checksum_sha256,media_variant,review_status,visibility,publication_status)
      VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11,$12,'active',$13)`,
      [artifact.id, project, artifact.type, title, JSON.stringify(artifact.tags), duration, size, artifact.mime, row.source_id, checksum, artifact.mediaVariant, artifact.reviewStatus, artifact.publicationStatus]);
    return artifact.id;
  });
  await deleteSourceArtifactTemporary(project, jobId, token, kind).catch(() => {});
  return { ok: true, id: completedId };
}

/** POST /internal/source-processing/:project/:jobId/heartbeat (no original check). */
export async function heartbeatJob(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const token = leaseToken(body);
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing SET lease_until=now()+($1 * interval '1 second'),updated_at=now()
    WHERE project=$2 AND id=$3 AND state='claimed' AND lease_token=$4 AND lease_until > now()
    RETURNING id`, [loadConfig().sourceProcessingLeaseSeconds, project, jobId, token]);
  if (!rows[0]) throw new HttpError(409, LEASE_NOT_ACTIVE);
  return { ok: true };
}

/**
 * PATCH /internal/source-processing/:project/:jobId/checkpoints
 * Keep resumable, bounded metadata while the worker has the lease.
 */
export async function saveCheckpoints(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const token = leaseToken(body);
  const trimPlan = optionalTrimPlan(body);
  const transcript = optionalString(body, "review_transcript", 200_000);
  const title = optionalString(body, "generated_title", 1_000);
  if (trimPlan === undefined && transcript === undefined && title === undefined) {
    // An old worker can still send only `srt_text`. Ignore it (#44).
    if ("srt_text" in body) return { ok: true };
    throw new HttpError(400, "At least one checkpoint is required");
  }
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing j
    SET trim_plan=COALESCE($1::jsonb,trim_plan), review_transcript=COALESCE($2,review_transcript),
        generated_title=COALESCE($3,generated_title), updated_at=now()
    WHERE project=$4 AND id=$5 AND state='claimed' AND lease_token=$6 AND lease_until > now()
      AND ${originalExists(ident)}
    RETURNING id`, [trimPlan ?? null, transcript ?? null, title ?? null, project, jobId, token]);
  if (!rows[0]) await leaseMiss(project, jobId, token);
  return { ok: true };
}

/**
 * POST /internal/source-processing/:project/:jobId/waiting
 * A partial worker must not say that a source is fully processed.
 */
export async function markWaiting(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const reason = optionalString(body, "reason", 1_000);
  if (!reason) throw new HttpError(400, "reason is required");
  const token = leaseToken(body);
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing j
    SET state='waiting',waiting_reason=$1,lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE project=$2 AND id=$3 AND state='claimed' AND lease_token=$4 AND lease_until > now()
      AND ${originalExists(ident)}
    RETURNING id`, [reason, project, jobId, token]);
  if (!rows[0]) await leaseMiss(project, jobId, token);
  return { ok: true };
}

/** POST /internal/source-processing/:project/:jobId/complete */
export async function completeJob(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const token = leaseToken(body);
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ source_id: string }[]>(`
    UPDATE ${ident}.source_processing j SET state='completed',lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3 AND j.lease_until > now()
      AND ${originalExists(ident)}
    RETURNING source_id`, [project, jobId, token]);
  const row = rows[0];
  if (!row) return await leaseMiss(project, jobId, token);
  return { ok: true, source_id: row.source_id };
}

/** POST /internal/source-processing/:project/:jobId/fail (no original check). */
export async function failJob(request: Request, project: string, jobId: string): Promise<Result> {
  authorize(request);
  const body = await readBody(request);
  const error = String(body.error ?? "worker failed").slice(0, 2000);
  const token = leaseToken(body);
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing SET state='failed',last_error=$1,lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE project=$2 AND id=$3 AND state='claimed' AND lease_token=$4 AND lease_until > now()
    RETURNING id`, [error, project, jobId, token]);
  if (!rows[0]) throw new HttpError(409, LEASE_NOT_ACTIVE);
  return { ok: true };
}
