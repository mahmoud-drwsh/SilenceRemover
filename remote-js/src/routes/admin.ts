/**
 * Admin endpoints under /admin/:admin_token/* - 1:1 port of the FastAPI admin
 * routes in remote/app.py (`refresh_admin_token`, `set_media_token`,
 * `list_admin_projects`, `list_admin_project_s3_storage`, the removed File
 * Browser 404 sentinel, and the admin SPA fallback).
 */

import { Hono } from "hono";
import type { Context } from "hono";
import { join, normalize, sep } from "node:path";
import { writeAdminAuditEvent } from "../audit.ts";
import {
  getMediaTokenPlaintext,
  rotateAdminToken,
  setMediaToken,
} from "../auth.ts";
import { getDb, schemaIdent } from "../db.ts";
import { getPeerIp, verifyAdminToken } from "../http.ts";
import { HttpError, SetMediaTokenRequestSchema } from "../schemas.ts";
import { storageProjectSizeTotals } from "../storage.ts";

export const adminRouter = new Hono();

const FRONTEND_ROOT = new URL("../../frontend/", import.meta.url).pathname;
const ADMIN_HTML = join(FRONTEND_ROOT, "admin.html");

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

function buildAuditRequest(c: Context) {
  return {
    peerIp: getPeerIp(c),
    userAgent: c.req.header("user-agent") ?? "",
  };
}

/* -------------------------------------------------------------------------- */
/* Token rotation                                                             */
/* -------------------------------------------------------------------------- */

async function refreshAdminTokenHandler(adminToken: string, c: Context) {
  await verifyAdminToken(c, adminToken);
  const newAdminToken = await rotateAdminToken();
  await writeAdminAuditEvent("token-admin", "refresh_admin_token", buildAuditRequest(c));
  return c.json({
    ok: true,
    admin_token: newAdminToken,
    admin_url: `/admin/${newAdminToken}/`,
    persisted: true,
    persistence: "postgres",
  });
}

adminRouter.post("/admin/:admin_token/api/refresh-admin-token", async (c) => {
  return refreshAdminTokenHandler(c.req.param("admin_token"), c);
});

adminRouter.post("/admin/:admin_token/api/refresh-token", async (c) => {
  return refreshAdminTokenHandler(c.req.param("admin_token"), c);
});

/* -------------------------------------------------------------------------- */
/* Media token                                                                */
/* -------------------------------------------------------------------------- */

adminRouter.post("/admin/:admin_token/api/media-token", async (c) => {
  const adminToken = c.req.param("admin_token");
  await verifyAdminToken(c, adminToken);

  const json = await c.req.json().catch(() => null);
  const parsed = SetMediaTokenRequestSchema.safeParse(json);
  if (!parsed.success) {
    throw new HttpError(400, "Invalid token payload");
  }
  const trimmed = parsed.data.token.trim();
  if (!trimmed) {
    throw new HttpError(400, "Project token cannot be empty");
  }
  await setMediaToken(trimmed);

  await writeAdminAuditEvent(
    "token-admin",
    "set_media_token",
    buildAuditRequest(c),
    { token_length: trimmed.length },
  );

  return c.json({
    ok: true,
    media_token: trimmed,
    persisted: true,
    persistence: "postgres-encrypted",
  });
});

/* -------------------------------------------------------------------------- */
/* Project stats                                                              */
/* -------------------------------------------------------------------------- */

adminRouter.get("/admin/:admin_token/api/projects", async (c) => {
  await verifyAdminToken(c, c.req.param("admin_token"));

  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<ProjectStatRow[]>(`
    SELECT
      project,
      COUNT(CASE WHEN type='audio' THEN 1 END) AS audio_total,
      SUM(CASE WHEN type='audio' AND tags::text LIKE '%"todo"%' THEN 1 ELSE 0 END) AS audio_todo,
      SUM(CASE WHEN type='audio' AND tags::text LIKE '%"ready"%' THEN 1 ELSE 0 END) AS audio_ready,
      SUM(CASE WHEN type='audio' AND tags::text LIKE '%"trash"%' THEN 1 ELSE 0 END) AS audio_trash,
      COUNT(CASE WHEN type='video' THEN 1 END) AS video_total,
      COALESCE(SUM(file_size), 0) AS total_bytes,
      MAX(created_at) AS last_updated
    FROM ${ident}.files
    GROUP BY project
    ORDER BY project
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

  return c.json({
    media_token: await getMediaTokenPlaintext(),
    projects,
  });
});

/* -------------------------------------------------------------------------- */
/* S3 storage totals                                                          */
/* -------------------------------------------------------------------------- */

adminRouter.get("/admin/:admin_token/api/projects/s3-storage", async (c) => {
  await verifyAdminToken(c, c.req.param("admin_token"));

  const totals = await storageProjectSizeTotals();
  const entries = Object.entries(totals);
  return c.json({
    projects: entries.map(([project, size]) => ({
      project,
      s3_storage_bytes: size,
    })),
    total_s3_storage_bytes: entries.reduce((acc, [, size]) => acc + size, 0),
  });
});

/* -------------------------------------------------------------------------- */
/* Removed File Browser route                                                 */
/* -------------------------------------------------------------------------- */

const FILE_BROWSER_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] as const;

for (const method of FILE_BROWSER_METHODS) {
  adminRouter.on(method, "/admin/:admin_token/files", async (c) => {
    await verifyAdminToken(c, c.req.param("admin_token"));
    throw new HttpError(404, "Admin File Browser has been removed");
  });
  adminRouter.on(method, "/admin/:admin_token/files/*", async (c) => {
    await verifyAdminToken(c, c.req.param("admin_token"));
    throw new HttpError(404, "Admin File Browser has been removed");
  });
}

/* -------------------------------------------------------------------------- */
/* Admin SPA fallback                                                         */
/* -------------------------------------------------------------------------- */

async function serveAdminFile(filePath: string): Promise<Response> {
  const file = Bun.file(filePath);
  if (!(await file.exists())) {
    throw new HttpError(404, "File not found");
  }
  return new Response(file, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

adminRouter.get("/admin/:admin_token/", async (c) => {
  await verifyAdminToken(c, c.req.param("admin_token"));
  return serveAdminFile(ADMIN_HTML);
});

adminRouter.get("/admin/:admin_token/*", async (c) => {
  const adminToken = c.req.param("admin_token");
  await verifyAdminToken(c, adminToken);

  // Allow direct loading of admin static assets (e.g., admin.html), but
  // default to admin.html for any other path so client-side routing works.
  const url = new URL(c.req.url);
  const prefix = `/admin/${adminToken}/`;
  const rest = url.pathname.startsWith(prefix)
    ? url.pathname.slice(prefix.length)
    : "";
  if (rest) {
    const candidate = normalize(join(FRONTEND_ROOT, rest));
    const rootWithSep = FRONTEND_ROOT.endsWith(sep)
      ? FRONTEND_ROOT
      : FRONTEND_ROOT + sep;
    if (candidate.startsWith(rootWithSep)) {
      const file = Bun.file(candidate);
      if (await file.exists()) {
        return serveAdminFile(candidate);
      }
    }
  }
  return serveAdminFile(ADMIN_HTML);
});
