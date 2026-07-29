/**
 * Media Manager service entrypoint.
 *
 * Mirrors the FastAPI lifespan in remote/app.py: validate config, verify the
 * Postgres metadata store and S3 bucket are reachable, then start the HTTP
 * server on port 8080 (overridable via PORT).
 */

import { Hono } from "hono";
import { closeDb, ensureDatabaseReady } from "./db.ts";
import { loadConfig } from "./config.ts";
import { ensureStorageBackendReady } from "./storage.ts";
import { securityHeaders } from "./security.ts";
import { adminRouter } from "./routes/admin.ts";
import { filesRouter } from "./routes/files.ts";
import { projectSpaRouter } from "./routes/projectSpa.ts";
import { streamRouter } from "./routes/stream.ts";
import { publicRouter } from "./routes/public.ts";
import { uploadsRouter, cleanupExpiredUploadSessions } from "./routes/uploads.ts";
import { originalsRouter } from "./routes/originals.ts";
import { HttpError } from "./schemas.ts";

const app = new Hono();

app.use("*", securityHeaders);

app.onError((err, c) => {
  if (err instanceof HttpError) {
    const headers = err.headers ?? {};
    return c.json({ detail: err.message }, err.status as 400, headers);
  }
  console.error("[ERROR]", err);
  return c.json({ detail: "Internal server error" }, 500);
});

app.notFound((c) => c.json({ detail: "Not Found" }, 404));

app.get("/healthz", (c) => c.json({ ok: true }));

app.route("/", adminRouter);
app.route("/", filesRouter);
app.route("/", streamRouter);
app.route("/", publicRouter);
app.route("/", uploadsRouter);
app.route("/", originalsRouter);
app.route("/", projectSpaRouter);

async function main(): Promise<void> {
  const config = loadConfig();
  console.log(
    `[startup] media-manager checking Postgres schema "${config.dbSchema}" and S3 bucket "${config.s3Bucket}" ...`,
  );
  await ensureDatabaseReady();
  await ensureStorageBackendReady();
  await cleanupExpiredUploadSessions();
  console.log("[startup] checks passed; listening on :" + config.port);

  const server = Bun.serve({
    port: config.port,
    hostname: "0.0.0.0",
    idleTimeout: 0,
    fetch: app.fetch,
    error(error) {
      console.error("[bun.serve error]", error);
      return new Response("Internal server error", { status: 500 });
    },
  });

  const shutdown = async (signal: NodeJS.Signals) => {
    console.log(`[shutdown] ${signal} received; closing server`);
    server.stop();
    await closeDb().catch(() => {});
    process.exit(0);
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  console.error("[startup-error]", err);
  process.exit(1);
});
