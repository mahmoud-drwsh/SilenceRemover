import { Hono } from "hono";
import { randomUUID } from "node:crypto";
import { getDb, schemaIdent } from "../db.ts";
import { verifyMediaToken } from "../http.ts";
import { HttpError } from "../schemas.ts";
import {
  deleteTemporaryRemux,
  presignTemporaryRemuxPut,
  promoteTemporaryRemux,
  temporaryRemuxHead,
  temporaryRemuxSha256,
  storageSha256,
} from "../storage.ts";
import { getExtensionForMime } from "../mime.ts";

export const remuxRouter = new Hono();
const SHA256 = /^[a-f0-9]{64}$/;

interface RemuxJob {
  id: string; project: string; video_id: string; source_id: string; subtitle_id: string;
  input_checksum_sha256: string; subtitle_checksum_sha256: string; state: string;
  lease_token: string | null; mime_type?: string; file_size?: number; title?: string | null;
}

async function job(project: string, id: string): Promise<RemuxJob | undefined> {
  const sql = getDb(); const ident = schemaIdent();
  return (await sql.unsafe<RemuxJob[]>(`
    SELECT j.*, f.mime_type, f.file_size, f.title
    FROM ${ident}.subtitle_remux_jobs j
    JOIN ${ident}.files f ON f.project=j.project AND f.id=j.video_id AND f.type='video'
    WHERE j.project=$1 AND j.id=$2`, [project, id]))[0];
}

function requireLease(row: RemuxJob | undefined, leaseToken: unknown): RemuxJob {
  if (!row) throw new HttpError(404, "Remux job not found");
  if (row.state !== "claimed" || !row.lease_token || leaseToken !== row.lease_token) {
    throw new HttpError(409, "Remux job lease is not active");
  }
  return row;
}

remuxRouter.post("/projects/:token/:project/api/remux/enqueue", async (c) => {
  const { token, project } = c.req.param(); await verifyMediaToken(token);
  const sql = getDb(); const ident = schemaIdent();
  const rows = await sql.unsafe<{ count: string }[]>(`
    WITH inserted AS (
      INSERT INTO ${ident}.subtitle_remux_jobs
        (id,project,video_id,source_id,subtitle_id,input_checksum_sha256,subtitle_checksum_sha256)
      SELECT md5(random()::text || clock_timestamp()::text || v.id), v.project, v.id, v.source_id, s.id,
             v.checksum_sha256, s.checksum_sha256
      FROM ${ident}.files v
      JOIN ${ident}.files s ON s.project=v.project AND s.type='subtitle'
        AND s.id=v.source_id || '-subtitles'
      WHERE v.project=$1 AND v.type='video' AND v.source_id IS NOT NULL
        AND v.checksum_sha256 IS NOT NULL AND s.checksum_sha256 IS NOT NULL
        AND NOT (v.tags @> '["trash"]'::jsonb)
      ON CONFLICT (project,video_id,input_checksum_sha256,subtitle_checksum_sha256) DO NOTHING
      RETURNING 1
    ) SELECT count(*)::text count FROM inserted`, [project]);
  return c.json({ ok: true, enqueued: Number(rows[0]?.count ?? 0) });
});

remuxRouter.post("/projects/:token/:project/api/remux/checksum/:videoId", async (c) => {
  const { token, project, videoId } = c.req.param(); await verifyMediaToken(token);
  const sql = getDb(); const ident = schemaIdent();
  const row = (await sql.unsafe<{ checksum_sha256: string | null; mime_type: string }[]>(
    `SELECT checksum_sha256,mime_type FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='video'`,
    [project, videoId],
  ))[0];
  if (!row) throw new HttpError(404, "Video not found");
  if (row.checksum_sha256) return c.json({ ok: true, checksum_sha256: row.checksum_sha256, repaired: false });
  const checksum = await storageSha256("video", project, videoId, getExtensionForMime(row.mime_type));
  const updated = await sql.unsafe<{ checksum_sha256: string }[]>(`
    UPDATE ${ident}.files SET checksum_sha256=$1
    WHERE project=$2 AND id=$3 AND type='video' AND checksum_sha256 IS NULL
    RETURNING checksum_sha256`, [checksum, project, videoId]);
  const current = updated[0]?.checksum_sha256 ?? (await sql.unsafe<{ checksum_sha256: string }[]>(
    `SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='video'`, [project,videoId],
  ))[0]?.checksum_sha256;
  return c.json({ ok: true, checksum_sha256: current, repaired: Boolean(updated[0]) });
});

remuxRouter.post("/projects/:token/:project/api/remux/claim", async (c) => {
  const { token, project } = c.req.param(); await verifyMediaToken(token);
  const sql = getDb(); const ident = schemaIdent(); const leaseToken = randomUUID();
  const rows = await sql.unsafe<RemuxJob[]>(`
    WITH candidate AS (
      SELECT id FROM ${ident}.subtitle_remux_jobs
      WHERE project=$1 AND attempts < 5
        AND (state IN ('pending','failed') OR (state='claimed' AND lease_until < now()))
      ORDER BY created_at, id FOR UPDATE SKIP LOCKED LIMIT 1
    )
    UPDATE ${ident}.subtitle_remux_jobs j SET state='claimed', attempts=attempts+1,
      lease_token=$2, lease_until=now()+interval '30 minutes', updated_at=now(), last_error=NULL
    FROM candidate WHERE j.id=candidate.id RETURNING j.*`, [project, leaseToken]);
  if (!rows[0]) return c.json({ ok: true, job: null });
  const row = await job(project, rows[0].id);
  return c.json({ ok: true, job: { ...row, lease_token: leaseToken } });
});

remuxRouter.post("/projects/:token/:project/api/remux/:jobId/upload", async (c) => {
  const { token, project, jobId } = c.req.param(); await verifyMediaToken(token);
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const row = requireLease(await job(project, jobId), body.lease_token);
  const size = Number(body.size); const checksum = String(body.checksum_sha256 ?? "").toLowerCase();
  if (!Number.isSafeInteger(size) || size <= 0 || !SHA256.test(checksum)) throw new HttpError(400, "Valid size and checksum_sha256 are required");
  const sql = getDb(); const ident = schemaIdent();
  await sql.unsafe(`UPDATE ${ident}.subtitle_remux_jobs SET output_file_size=$1,output_checksum_sha256=$2,updated_at=now() WHERE id=$3`, [size, checksum, row.id]);
  return c.json({ ok: true, upload_url: await presignTemporaryRemuxPut(project, jobId) });
});

remuxRouter.post("/projects/:token/:project/api/remux/:jobId/complete", async (c) => {
  const { token, project, jobId } = c.req.param(); await verifyMediaToken(token);
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const row = requireLease(await job(project, jobId), body.lease_token);
  const sql = getDb(); const ident = schemaIdent();
  const fresh = (await sql.unsafe<{ checksum_sha256: string | null; mime_type: string }[]>(`SELECT checksum_sha256,mime_type FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='video'`, [project,row.video_id]))[0];
  const currentSubtitle = (await sql.unsafe<{ checksum_sha256: string | null }[]>(`SELECT checksum_sha256 FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='subtitle'`, [project,row.subtitle_id]))[0];
  if (!fresh || fresh.checksum_sha256 !== row.input_checksum_sha256 || currentSubtitle?.checksum_sha256 !== row.subtitle_checksum_sha256) {
    await sql.unsafe(`UPDATE ${ident}.subtitle_remux_jobs SET state='stale',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=$1`, [row.id]);
    throw new HttpError(409, "Video or subtitle changed after this job was queued");
  }
  const output = (await sql.unsafe<{ output_file_size: number | null; output_checksum_sha256: string | null }[]>(`SELECT output_file_size,output_checksum_sha256 FROM ${ident}.subtitle_remux_jobs WHERE id=$1`, [row.id]))[0];
  const head = await temporaryRemuxHead(project, jobId);
  if (!head || head.size !== Number(output?.output_file_size)) throw new HttpError(400, "Temporary remux size did not match");
  const actualChecksum = await temporaryRemuxSha256(project, jobId);
  if (!output?.output_checksum_sha256 || actualChecksum !== output.output_checksum_sha256) throw new HttpError(400, "Temporary remux checksum did not match");
  await promoteTemporaryRemux(project, jobId, row.video_id, getExtensionForMime(fresh.mime_type));
  await sql.unsafe(`UPDATE ${ident}.files SET file_size=$1,checksum_sha256=$2 WHERE project=$3 AND id=$4 AND type='video'`, [head.size,actualChecksum,project,row.video_id]);
  await sql.unsafe(`UPDATE ${ident}.subtitle_remux_jobs SET state='completed',lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=$1`, [row.id]);
  await deleteTemporaryRemux(project, jobId).catch(() => {});
  return c.json({ ok: true, video_id: row.video_id, checksum_sha256: actualChecksum });
});

remuxRouter.post("/projects/:token/:project/api/remux/:jobId/fail", async (c) => {
  const { token, project, jobId } = c.req.param(); await verifyMediaToken(token);
  const body = await c.req.json().catch(() => ({})) as Record<string, unknown>;
  const row = requireLease(await job(project, jobId), body.lease_token);
  const error = String(body.error ?? "worker failed").slice(0, 2000);
  const sql = getDb(); const ident = schemaIdent();
  await sql.unsafe(`UPDATE ${ident}.subtitle_remux_jobs SET state='failed',last_error=$1,lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=$2`, [error,row.id]);
  return c.json({ ok: true });
});

remuxRouter.get("/projects/:token/:project/api/remux/status", async (c) => {
  const { token, project } = c.req.param(); await verifyMediaToken(token);
  const sql = getDb(); const ident = schemaIdent();
  const states = await sql.unsafe<{ state: string; count: string }[]>(`SELECT state,count(*)::text count FROM ${ident}.subtitle_remux_jobs WHERE project=$1 GROUP BY state ORDER BY state`, [project]);
  const eligible = await sql.unsafe<{ videos: string; subtitles: string }[]>(`SELECT count(*) FILTER (WHERE type='video' AND source_id IS NOT NULL)::text videos,count(*) FILTER (WHERE type='subtitle')::text subtitles FROM ${ident}.files WHERE project=$1`, [project]);
  return c.json({ ok: true, states: Object.fromEntries(states.map((r) => [r.state, Number(r.count)])), inventory: { videos: Number(eligible[0]?.videos ?? 0), subtitles: Number(eligible[0]?.subtitles ?? 0) } });
});
