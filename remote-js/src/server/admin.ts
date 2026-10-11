/**
 * Admin routes under /admin/:token/* (#63). Same behavior as
 * the old Bun service file routes/admin.ts and the two admin routes in
 * the old Bun service file routes/sourceProcessing.ts.
 *
 * Every admin route checks the admin token first (verifyAdminToken), so each
 * route can answer 429 (rate limit for the client IP) or 401.
 *
 * The old catch-all behavior (a GET of a non-route admin path gets the admin
 * page; other methods get the JSON 404) is in src/server/adminPaths.ts,
 * which server.ts applies before Next.js routes the request.
 */

import { writeAdminAuditEvent, type AuditEventRequest } from "./audit.ts";
import { getMediaTokenPlaintext, rotateAdminToken, setMediaToken } from "./auth.ts";
import { requestClientIp } from "./clientIp.ts";
import { isSourceProcessingEnabled } from "./config.ts";
import { getDb, schemaIdent } from "./db.ts";
import { errorResponse, hasTrailingSlash, json, notFound, verifyAdminToken } from "./http.ts";
import { HttpError, SetMediaTokenRequestSchema } from "./schemas.ts";
import { serializeSourceProcessingJob, type SourceProcessingJob } from "./sourceProcessing.ts";
import { storageProjectSizeTotals } from "./storage.ts";

/** Route context of every handler under app/admin/[token]/. */
export interface AdminContext<P extends Record<string, unknown> = Record<string, never>> {
  params: Promise<{ token: string } & P>;
}

/** Check the admin token in the URL for the client IP of this request. */
export async function requireAdmin(request: Request, token: string): Promise<void> {
  await verifyAdminToken(requestClientIp(request), token);
}

function auditRequest(request: Request): AuditEventRequest {
  return {
    peerIp: requestClientIp(request),
    userAgent: request.headers.get("user-agent") ?? "",
  };
}

type AdminHandler<P extends Record<string, unknown>> = (
  request: Request,
  params: { token: string } & P,
) => Response | Promise<Response>;

/**
 * Wrap an admin API handler: the error mapping and the strict trailing-slash
 * rule of `route()`. (server.ts already sends a GET with a trailing slash to
 * the admin page and answers other methods with the JSON 404.)
 */
export function adminRoute<P extends Record<string, unknown> = Record<string, never>>(
  handler: AdminHandler<P>,
): (request: Request, context: AdminContext<P>) => Promise<Response> {
  return async (request, context) => {
    if (hasTrailingSlash(request)) return notFound();
    try {
      return await handler(request, await context.params);
    } catch (err) {
      return errorResponse(err);
    }
  };
}

/**
 * Handler for the removed Admin File Browser (`/admin/:token/files` and
 * `/admin/:token/files/*`, all methods, also with a trailing slash): token
 * check, then 404.
 */
export async function removedFileBrowserRoute(
  request: Request,
  context: { params: Promise<{ token: string }> },
): Promise<Response> {
  try {
    const { token } = await context.params;
    await requireAdmin(request, token);
    throw new HttpError(404, "Admin File Browser has been removed");
  } catch (err) {
    return errorResponse(err);
  }
}

/* -------------------------------------------------------------------------- */
/* Tokens                                                                     */
/* -------------------------------------------------------------------------- */

/** POST /admin/:token/api/refresh-admin-token and its alias refresh-token. */
export const refreshAdminToken = adminRoute(async (request, { token }) => {
  await requireAdmin(request, token);
  const newAdminToken = await rotateAdminToken();
  await writeAdminAuditEvent("token-admin", "refresh_admin_token", auditRequest(request));
  return json({
    ok: true,
    admin_token: newAdminToken,
    admin_url: `/admin/${newAdminToken}/`,
    persisted: true,
    persistence: "postgres",
  });
});

/** POST /admin/:token/api/media-token */
export const setMediaTokenRoute = adminRoute(async (request, { token }) => {
  await requireAdmin(request, token);
  const body: unknown = await request.json().catch(() => null);
  const parsed = SetMediaTokenRequestSchema.safeParse(body);
  if (!parsed.success) {
    throw new HttpError(400, "Invalid token payload");
  }
  const trimmed = parsed.data.token.trim();
  if (!trimmed) {
    throw new HttpError(400, "Project token cannot be empty");
  }
  await setMediaToken(trimmed);
  await writeAdminAuditEvent("token-admin", "set_media_token", auditRequest(request), {
    token_length: trimmed.length,
  });
  return json({
    ok: true,
    media_token: trimmed,
    persisted: true,
    persistence: "postgres-encrypted",
  });
});

/* -------------------------------------------------------------------------- */
/* Project statistics                                                         */
/* -------------------------------------------------------------------------- */

interface ProjectStatRow {
  project: string;
  audio_total: number | string | null;
  audio_todo: number | string | null;
  audio_ready: number | string | null;
  audio_trash: number | string | null;
  video_total: number | string | null;
  total_bytes: number | string | null;
  last_updated: Date | string | null;
}

function toInt(value: number | string | null): number {
  if (value == null) return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function isoOrNull(value: Date | string | null): string | null {
  if (value == null) return null;
  if (value instanceof Date) return value.toISOString();
  return String(value);
}

/** GET /admin/:token/api/projects */
export const listProjects = adminRoute(async (request, { token }) => {
  await requireAdmin(request, token);
  const sql = getDb();
  const ident = schemaIdent();
  // The audio counts use a text match on the tags, as in the old service.
  const rows = await sql.unsafe<ProjectStatRow[]>(`
    SELECT
      f.project,
      COUNT(CASE WHEN f.type='audio' THEN 1 END) AS audio_total,
      SUM(CASE WHEN f.type='audio' AND f.tags::text LIKE '%"todo"%' THEN 1 ELSE 0 END) AS audio_todo,
      SUM(CASE WHEN f.type='audio' AND f.tags::text LIKE '%"ready"%' THEN 1 ELSE 0 END) AS audio_ready,
      SUM(CASE WHEN f.type='audio' AND f.tags::text LIKE '%"trash"%' THEN 1 ELSE 0 END) AS audio_trash,
      COUNT(CASE WHEN f.type='video' THEN 1 END) AS video_total,
      COALESCE(SUM(f.file_size), 0) AS total_bytes,
      MAX(f.created_at) AS last_updated
    FROM ${ident}.files f
    GROUP BY f.project
    ORDER BY f.project
  `);

  const projects = rows.map((row) => ({
    project: row.project,
    audio: {
      todo: toInt(row.audio_todo),
      ready: toInt(row.audio_ready),
      trash: toInt(row.audio_trash),
      total: toInt(row.audio_total),
    },
    video: {
      total: toInt(row.video_total),
    },
    storage_bytes: toInt(row.total_bytes),
    last_updated: isoOrNull(row.last_updated),
  }));

  return json({
    media_token: await getMediaTokenPlaintext(),
    projects,
  });
});

/** GET /admin/:token/api/projects/s3-storage */
export const listS3Storage = adminRoute(async (request, { token }) => {
  await requireAdmin(request, token);
  const totals = await storageProjectSizeTotals();
  const entries = Object.entries(totals);
  return json({
    projects: entries.map(([project, size]) => ({
      project,
      s3_storage_bytes: size,
    })),
    total_s3_storage_bytes: entries.reduce((acc, [, size]) => acc + size, 0),
  });
});

/* -------------------------------------------------------------------------- */
/* Source processing                                                          */
/* -------------------------------------------------------------------------- */

/** GET /admin/:token/api/projects/:project/source-processing/status */
export const sourceProcessingStatus = adminRoute<{ project: string }>(async (request, { token, project }) => {
  await requireAdmin(request, token);
  const sql = getDb();
  const ident = schemaIdent();
  const states = await sql.unsafe<{ state: string; count: string }[]>(
    `SELECT state,count(*)::text count FROM ${ident}.source_processing WHERE project=$1 GROUP BY state ORDER BY state`,
    [project],
  );
  const failed = await sql.unsafe<SourceProcessingJob[]>(
    `SELECT * FROM ${ident}.source_processing WHERE project=$1 AND state='failed' ORDER BY updated_at,id LIMIT 100`,
    [project],
  );
  const waiting = await sql.unsafe<SourceProcessingJob[]>(
    `SELECT * FROM ${ident}.source_processing WHERE project=$1 AND state='waiting' ORDER BY updated_at,id LIMIT 100`,
    [project],
  );
  const stateMap = Object.fromEntries(states.map((row) => [row.state, Number(row.count)]));
  return json({
    ok: true,
    enabled: isSourceProcessingEnabled(project),
    total: Object.values(stateMap).reduce((a, b) => a + b, 0),
    states: stateMap,
    failed: failed.map(serializeSourceProcessingJob),
    waiting: waiting.map(serializeSourceProcessingJob),
  });
});

/** POST /admin/:token/api/projects/:project/source-processing/:jobId/retry */
export const retrySourceProcessingJob = adminRoute<{ project: string; jobId: string }>(
  async (request, { token, project, jobId }) => {
    await requireAdmin(request, token);
    const sql = getDb();
    const ident = schemaIdent();
    const rows = await sql.unsafe<{ id: string }[]>(`
      UPDATE ${ident}.source_processing SET state='pending',attempts=0,last_error=NULL,waiting_reason=NULL,
        lease_token=NULL,lease_until=NULL,updated_at=now()
      WHERE project=$1 AND id=$2 AND state IN ('failed','waiting') RETURNING id`, [project, jobId]);
    if (!rows[0]) {
      throw new HttpError(409, "Only failed or waiting source-processing jobs can be retried");
    }
    return json({ ok: true });
  },
);
