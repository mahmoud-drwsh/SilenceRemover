/** Durable control-plane queue for server-owned source processing. */

import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { Hono } from "hono";
import { loadConfig, isSourceProcessingEnabled } from "../config.ts";
import { getDb, schemaIdent } from "../db.ts";
import { verifyAdminToken } from "../http.ts";
import { getExtensionForMime } from "../mime.ts";
import { HttpError } from "../schemas.ts";
import { deleteSourceArtifactTemporary, presignOriginalDownload, presignSourceArtifactPut, promoteSourceArtifact, sourceArtifactTemporaryHead, sourceArtifactTemporarySha256, storageGetProjectOverlayLogo } from "../storage.ts";

export const sourceProcessingRouter = new Hono();

interface SourceProcessingJob {
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
  srt_text: string | null;
  waiting_reason: string | null;
  last_error: string | null;
}

interface OriginalForWorker {
  mime_type: string;
  original_filename: string | null;
}

const SHA256 = /^[a-f0-9]{64}$/;

function artifactIdentity(kind: unknown, sourceId: string): { type: "audio" | "subtitle" | "video"; id: string; mime: string; ext: string; tags: string[]; mediaVariant: string | null; reviewStatus: string | null; publicationStatus: string | null } {
  if (kind === "review_audio") return { type: "audio", id: sourceId, mime: "audio/ogg", ext: ".ogg", tags: ["todo"], mediaVariant: null, reviewStatus: "todo", publicationStatus: null };
  if (kind === "subtitle") return { type: "subtitle", id: `${sourceId}-subtitles`, mime: "application/x-subrip", ext: ".srt", tags: [], mediaVariant: null, reviewStatus: null, publicationStatus: null };
  if (kind === "no_overlay_video") return { type: "video", id: `${sourceId}-no-overlay`, mime: "video/mp4", ext: ".mp4", tags: ["no-overlay"], mediaVariant: "no-overlay", reviewStatus: null, publicationStatus: "published" };
  // A source is rendered only after its reviewer has approved the audio title,
  // so the final is immediately publishable under the existing tag contract.
  if (kind === "overlaid_video") return { type: "video", id: sourceId, mime: "video/mp4", ext: ".mp4", tags: [], mediaVariant: "pipeline-final", reviewStatus: null, publicationStatus: "published" };
  throw new HttpError(400, "Unsupported source-processing artifact kind");
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

function serializeJob(row: SourceProcessingJob): SourceProcessingJob {
  return { ...row, trim_plan: jsonObject(row.trim_plan) };
}

function workerTokenDigest(value: string): Buffer {
  return createHash("sha256").update(value).digest();
}

export function verifySourceProcessingWorkerToken(header: string | undefined): void {
  const expected = loadConfig().sourceProcessingWorkerToken;
  if (!header || !expected || !timingSafeEqual(workerTokenDigest(header), workerTokenDigest(expected))) {
    throw new HttpError(401, "Invalid source-processing worker token");
  }
}

function leaseToken(body: Record<string, unknown>): string {
  const value = String(body.lease_token ?? "");
  if (!value) throw new HttpError(409, "Source-processing job lease is not active");
  return value;
}

function optionalString(body: Record<string, unknown>, key: string, limit: number): string | undefined {
  if (!(key in body)) return undefined;
  const value = body[key];
  if (typeof value !== "string" || value.length > limit) {
    throw new HttpError(400, `${key} must be a string no longer than ${limit} characters`);
  }
  return value;
}

/** JSON persisted with a job is bounded control-plane metadata, never media bytes. */
function optionalTrimPlan(body: Record<string, unknown>): string | undefined {
  if (!("trim_plan" in body)) return undefined;
  const value = body.trim_plan;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new HttpError(400, "trim_plan must be an object");
  }
  const encoded = JSON.stringify(value);
  if (encoded.length > 64 * 1024) throw new HttpError(400, "trim_plan is too large");
  return encoded;
}

/** The review queue owns the final human-approved title. */
async function approvedAudioTitle(sql: { unsafe: Function }, ident: string, project: string, sourceId: string): Promise<string | null> {
  const row = (await sql.unsafe(`
    SELECT title FROM ${ident}.files a
    WHERE a.project=$1 AND a.id=$2 AND a.type='audio'
      AND (CASE WHEN jsonb_typeof(a.tags)='string' THEN (a.tags #>> '{}')::jsonb ELSE a.tags END) @> '["ready"]'::jsonb
      AND NOT ((CASE WHEN jsonb_typeof(a.tags)='string' THEN (a.tags #>> '{}')::jsonb ELSE a.tags END) @> '["trash"]'::jsonb)
    LIMIT 1`, [project, sourceId]) as Array<{ title: string }>)[0];
  return row?.title?.trim() || null;
}

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

/** Recover only interrupted original completions, never historical originals. */
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

sourceProcessingRouter.post("/internal/source-processing/:project/claim", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project } = c.req.param();
  if (!isSourceProcessingEnabled(project)) return c.json({ ok: true, job: null });
  const sql = getDb(); const ident = schemaIdent(); const leaseToken = randomUUID();
  const leaseSeconds = loadConfig().sourceProcessingLeaseSeconds;
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
                AND a.type='audio'
                AND (CASE WHEN jsonb_typeof(a.tags)='string' THEN (a.tags #>> '{}')::jsonb ELSE a.tags END) @> '["ready"]'::jsonb
                AND NOT ((CASE WHEN jsonb_typeof(a.tags)='string' THEN (a.tags #>> '{}')::jsonb ELSE a.tags END) @> '["trash"]'::jsonb)
            )
          )
        )
      ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE ${ident}.source_processing j
    SET state='claimed',attempts=attempts+1,lease_token=$2,
        lease_until=now()+($3 * interval '1 second'),last_error=NULL,updated_at=now()
    FROM candidate WHERE j.id=candidate.id RETURNING j.*`, [project, leaseToken, leaseSeconds]);
  const job = rows[0];
  if (!job) return c.json({ ok: true, job: null });
  const original = (await sql.unsafe<OriginalForWorker[]>(`
    SELECT mime_type,original_filename FROM ${ident}.files
    WHERE project=$1 AND id=$2 AND type='original' AND checksum_sha256=$3`,
    [project, job.source_id, job.original_checksum_sha256]))[0];
  if (!original) {
    await sql.unsafe(`UPDATE ${ident}.source_processing SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=$1`, [job.id]);
    return c.json({ ok: true, job: null });
  }
  const ext = getExtensionForMime(original.mime_type);
  const filename = original.original_filename ?? `${job.source_id}${ext}`;
  return c.json({ ok: true, job: {
    ...serializeJob(job),
    lease_token: leaseToken,
    original_download_url: await presignOriginalDownload(project, job.source_id, ext, filename),
    original_filename: filename,
    review_audio_uploaded: Boolean((await sql.unsafe<{ id: string }[]>(`SELECT id FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='audio'`, [project, job.source_id]))[0]),
    subtitle_uploaded: Boolean((await sql.unsafe<{ id: string }[]>(`SELECT id FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='subtitle'`, [project, `${job.source_id}-subtitles`]))[0]),
    no_overlay_uploaded: Boolean((await sql.unsafe<{ id: string }[]>(`SELECT id FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='video'`, [project, `${job.source_id}-no-overlay`]))[0]),
    overlaid_uploaded: Boolean((await sql.unsafe<{ id: string }[]>(`SELECT id FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='video'`, [project, job.source_id]))[0]),
    approved_title: (await sql.unsafe<{ title: string }[]>(`
      SELECT title FROM ${ident}.files a
      WHERE a.project=$1 AND a.id=$2 AND a.type='audio'
        AND (CASE WHEN jsonb_typeof(a.tags)='string' THEN (a.tags #>> '{}')::jsonb ELSE a.tags END) @> '["ready"]'::jsonb
        AND NOT ((CASE WHEN jsonb_typeof(a.tags)='string' THEN (a.tags #>> '{}')::jsonb ELSE a.tags END) @> '["trash"]'::jsonb)
      LIMIT 1`, [project, job.source_id]))[0]?.title ?? null,
  } });
});

/** The worker obtains the current project logo through its lease-fenced channel. */
sourceProcessingRouter.get("/internal/source-processing/:project/:jobId/overlay-logo", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const token = c.req.header("X-Source-Processing-Lease-Token") ?? "";
  const sql = getDb(); const ident = schemaIdent();
  const row = (await sql.unsafe<{ id: string }[]>(`
    SELECT j.id FROM ${ident}.source_processing j
    WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3
      AND j.lease_until > now()
      AND EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
        AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)`, [project, jobId, token]))[0];
  if (!row) throw new HttpError(409, "Source-processing job lease is not active");
  const body = await storageGetProjectOverlayLogo(project);
  if (!body) throw new HttpError(404, "Project overlay logo content not found");
  return new Response(body, { headers: { "Content-Type": "image/png", "Cache-Control": "no-store" } });
});

sourceProcessingRouter.post("/internal/source-processing/:project/:jobId/artifacts/initiate", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const token = leaseToken(body); const size = Number(body.size); const checksum = String(body.checksum_sha256 ?? "").toLowerCase(); const title = String(body.title ?? "");
  if (!Number.isSafeInteger(size) || size <= 0 || !SHA256.test(checksum)) throw new HttpError(400, "Valid size and checksum_sha256 are required");
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<SourceProcessingJob[]>(`
    SELECT * FROM ${ident}.source_processing j WHERE project=$1 AND id=$2 AND state='claimed'
      AND lease_token=$3 AND lease_until > now()
      AND EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
        AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)`, [project, jobId, token]);
  const row = rows[0]; if (!row) throw new HttpError(409, "Source-processing job lease is not active");
  const artifact = artifactIdentity(body.kind, row.source_id);
  const existing = (await sql.unsafe<{ checksum_sha256: string | null }[]>(`SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`, [project, artifact.id, artifact.type]))[0];
  if (existing) {
    if (existing.checksum_sha256 === checksum) return c.json({ ok: true, already_uploaded: true, id: artifact.id });
    throw new HttpError(409, "A different artifact already exists for this source");
  }
  if (artifact.type === "audio" && (!row.generated_title || String(body.title ?? "") !== row.generated_title)) throw new HttpError(409, "Review audio title must match the checkpointed title");
  if (artifact.type === "video") {
    const approved = await approvedAudioTitle(sql, ident, project, row.source_id);
    if (!approved || title !== approved) throw new HttpError(409, "Video title must match the approved review title");
  }
  if (artifact.type === "subtitle" && (!row.srt_text || createHash("sha256").update(row.srt_text).digest("hex") !== checksum)) throw new HttpError(409, "Subtitle bytes must match the checkpointed SRT");
  return c.json({ ok: true, id: artifact.id, upload_url: await presignSourceArtifactPut(project, jobId, token, String(body.kind), artifact.mime) });
});

sourceProcessingRouter.post("/internal/source-processing/:project/:jobId/artifacts/complete", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const token = leaseToken(body); const size = Number(body.size); const checksum = String(body.checksum_sha256 ?? "").toLowerCase();
  if (!Number.isSafeInteger(size) || size <= 0 || !SHA256.test(checksum)) throw new HttpError(400, "Valid size and checksum_sha256 are required");
  const duration = Number(body.duration ?? 0);
  if (!Number.isFinite(duration) || duration < 0 || duration > 24 * 60 * 60) throw new HttpError(400, "duration must be a valid media duration");
  const sql = getDb(); const ident = schemaIdent(); const kind = String(body.kind); const title = String(body.title ?? "");
  const completedId = await sql.begin(async (tx) => {
    const rows = await tx.unsafe<SourceProcessingJob[]>(`SELECT * FROM ${ident}.source_processing j WHERE project=$1 AND id=$2 AND state='claimed' AND lease_token=$3 AND lease_until > now() AND EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256) FOR UPDATE`, [project, jobId, token]);
    const row = rows[0]; if (!row) throw new HttpError(409, "Source-processing job lease is not active");
    const artifact = artifactIdentity(body.kind, row.source_id);
    if (artifact.type === "audio" && (!row.generated_title || title !== row.generated_title)) throw new HttpError(409, "Review audio title must match the checkpointed title");
    if (artifact.type === "video") {
      const approved = await approvedAudioTitle(tx, ident, project, row.source_id);
      if (!approved || title !== approved) throw new HttpError(409, "Video title must match the approved review title");
    }
    if (artifact.type === "subtitle" && (!row.srt_text || createHash("sha256").update(row.srt_text).digest("hex") !== checksum)) throw new HttpError(409, "Subtitle bytes must match the checkpointed SRT");
    const existing = (await tx.unsafe<{ checksum_sha256: string | null }[]>(`SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`, [project, artifact.id, artifact.type]))[0];
    if (existing) {
      if (existing.checksum_sha256 === checksum) return artifact.id;
      throw new HttpError(409, "A different artifact already exists for this source");
    }
    const head = await sourceArtifactTemporaryHead(project, jobId, token, kind);
    if (!head || head.size !== size || await sourceArtifactTemporarySha256(project, jobId, token, kind) !== checksum) throw new HttpError(400, "Uploaded artifact verification failed");
    await promoteSourceArtifact(project, jobId, token, kind, artifact.type, artifact.id, artifact.ext, artifact.mime);
    await tx.unsafe(`INSERT INTO ${ident}.files (id,project,type,title,tags,duration,file_size,mime_type,source_id,checksum_sha256,media_variant,review_status,visibility,publication_status) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11,$12,'active',$13)`, [artifact.id, project, artifact.type, title, JSON.stringify(artifact.tags), duration, size, artifact.mime, row.source_id, checksum, artifact.mediaVariant, artifact.reviewStatus, artifact.publicationStatus]);
    return artifact.id;
  });
  await deleteSourceArtifactTemporary(project, jobId, token, kind).catch(() => {});
  return c.json({ ok: true, id: completedId });
});

sourceProcessingRouter.post("/internal/source-processing/:project/:jobId/heartbeat", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing SET lease_until=now()+($1 * interval '1 second'),updated_at=now()
    WHERE project=$2 AND id=$3 AND state='claimed' AND lease_token=$4 AND lease_until > now()
    RETURNING id`, [loadConfig().sourceProcessingLeaseSeconds, project, jobId, leaseToken(body)]);
  if (!rows[0]) throw new HttpError(409, "Source-processing job lease is not active");
  return c.json({ ok: true });
});

/** Store resumable, bounded metadata while the worker still owns the lease. */
sourceProcessingRouter.patch("/internal/source-processing/:project/:jobId/checkpoints", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const token = leaseToken(body);
  const trimPlan = optionalTrimPlan(body);
  const transcript = optionalString(body, "review_transcript", 200_000);
  const title = optionalString(body, "generated_title", 1_000);
  const srt = optionalString(body, "srt_text", 500_000);
  if (trimPlan === undefined && transcript === undefined && title === undefined && srt === undefined) {
    throw new HttpError(400, "At least one checkpoint is required");
  }
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing j
    SET trim_plan=COALESCE($1::jsonb,trim_plan), review_transcript=COALESCE($2,review_transcript),
        generated_title=COALESCE($3,generated_title), srt_text=COALESCE($4,srt_text), updated_at=now()
    WHERE project=$5 AND id=$6 AND state='claimed' AND lease_token=$7 AND lease_until > now()
      AND EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
        AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)
    RETURNING id`, [trimPlan ?? null, transcript ?? null, title ?? null, srt ?? null, project, jobId, token]);
  if (!rows[0]) {
    const stale = await sql.unsafe<{ id: string }[]>(`
      UPDATE ${ident}.source_processing j SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now()
      WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3 AND j.lease_until > now()
        AND NOT EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
          AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)
      RETURNING id`, [project, jobId, token]);
    if (stale[0]) throw new HttpError(409, "Original changed after source processing was queued");
    throw new HttpError(409, "Source-processing job lease is not active");
  }
  return c.json({ ok: true });
});

/** A partial worker must not claim that a source is fully processed. */
sourceProcessingRouter.post("/internal/source-processing/:project/:jobId/waiting", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const reason = optionalString(body, "reason", 1_000);
  if (!reason) throw new HttpError(400, "reason is required");
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing j
    SET state='waiting',waiting_reason=$1,lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE project=$2 AND id=$3 AND state='claimed' AND lease_token=$4 AND lease_until > now()
      AND EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
        AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)
    RETURNING id`, [reason, project, jobId, leaseToken(body)]);
  if (!rows[0]) {
    const stale = await sql.unsafe<{ id: string }[]>(`
      UPDATE ${ident}.source_processing j SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now()
      WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3 AND j.lease_until > now()
        AND NOT EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
          AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)
      RETURNING id`, [project, jobId, leaseToken(body)]);
    if (stale[0]) throw new HttpError(409, "Original changed after source processing was queued");
    throw new HttpError(409, "Source-processing job lease is not active");
  }
  return c.json({ ok: true });
});

sourceProcessingRouter.post("/internal/source-processing/:project/:jobId/complete", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const token = leaseToken(body); const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ source_id: string }[]>(`
    UPDATE ${ident}.source_processing j SET state='completed',lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3 AND j.lease_until > now()
      AND EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
        AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)
    RETURNING source_id`, [project, jobId, token]);
  if (!rows[0]) {
    const stale = await sql.unsafe<{ id: string }[]>(`
      UPDATE ${ident}.source_processing j SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now()
      WHERE j.project=$1 AND j.id=$2 AND j.state='claimed' AND j.lease_token=$3 AND j.lease_until > now()
        AND NOT EXISTS (SELECT 1 FROM ${ident}.files f WHERE f.project=j.project AND f.id=j.source_id
          AND f.type='original' AND f.checksum_sha256=j.original_checksum_sha256)
      RETURNING id`, [project, jobId, token]);
    if (stale[0]) throw new HttpError(409, "Original changed after source processing was queued");
    throw new HttpError(409, "Source-processing job lease is not active");
  }
  return c.json({ ok: true, source_id: rows[0].source_id });
});

sourceProcessingRouter.post("/internal/source-processing/:project/:jobId/fail", async (c) => {
  verifySourceProcessingWorkerToken(c.req.header("X-Source-Processing-Token"));
  const { project, jobId } = c.req.param();
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const error = String(body.error ?? "worker failed").slice(0, 2000);
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing SET state='failed',last_error=$1,lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE project=$2 AND id=$3 AND state='claimed' AND lease_token=$4 AND lease_until > now()
    RETURNING id`, [error, project, jobId, leaseToken(body)]);
  if (!rows[0]) throw new HttpError(409, "Source-processing job lease is not active");
  return c.json({ ok: true });
});

sourceProcessingRouter.get("/admin/:admin_token/api/projects/:project/source-processing/status", async (c) => {
  await verifyAdminToken(c, c.req.param("admin_token"));
  const { project } = c.req.param(); const sql = getDb(); const ident = schemaIdent();
  const states = await sql.unsafe<{ state: string; count: string }[]>(
    `SELECT state,count(*)::text count FROM ${ident}.source_processing WHERE project=$1 GROUP BY state ORDER BY state`, [project],
  );
  const failed = await sql.unsafe<SourceProcessingJob[]>(
    `SELECT * FROM ${ident}.source_processing WHERE project=$1 AND state='failed' ORDER BY updated_at,id LIMIT 100`, [project],
  );
  const waiting = await sql.unsafe<SourceProcessingJob[]>(
    `SELECT * FROM ${ident}.source_processing WHERE project=$1 AND state='waiting' ORDER BY updated_at,id LIMIT 100`, [project],
  );
  const stateMap = Object.fromEntries(states.map((row) => [row.state, Number(row.count)]));
  return c.json({ ok: true, enabled: isSourceProcessingEnabled(project), total: Object.values(stateMap).reduce((a, b) => a + b, 0), states: stateMap, failed: failed.map(serializeJob), waiting: waiting.map(serializeJob) });
});

sourceProcessingRouter.post("/admin/:admin_token/api/projects/:project/source-processing/:jobId/retry", async (c) => {
  await verifyAdminToken(c, c.req.param("admin_token"));
  const { project, jobId } = c.req.param(); const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ id: string }[]>(`
    UPDATE ${ident}.source_processing SET state='pending',attempts=0,last_error=NULL,waiting_reason=NULL,
      lease_token=NULL,lease_until=NULL,updated_at=now()
    WHERE project=$1 AND id=$2 AND state IN ('failed','waiting') RETURNING id`, [project, jobId]);
  if (!rows[0]) throw new HttpError(409, "Only failed or waiting source-processing jobs can be retried");
  return c.json({ ok: true });
});
