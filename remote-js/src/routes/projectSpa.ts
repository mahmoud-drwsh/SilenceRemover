/**
 * Project-scoped static and SPA routes:
 *   - GET /projects/:token/:project/video-player
 *   - GET /projects/:token/:project/static/...
 *   - GET /projects/:token/:project/                 (SPA fallback)
 *   - GET /projects/:token/:project/...path          (SPA fallback)
 *
 * All routes require a valid project token.
 */

import { Hono } from "hono";
import { join, normalize, sep } from "node:path";
import { verifyMediaToken } from "../http.ts";
import { HttpError } from "../schemas.ts";

export const projectSpaRouter = new Hono();

const FRONTEND_ROOT = new URL("../../frontend/", import.meta.url).pathname;
const INDEX_HTML = join(FRONTEND_ROOT, "index.html");
const VIDEO_PLAYER_HTML = join(FRONTEND_ROOT, "video-player.html");

function contentTypeFor(filePath: string): string {
  const lower = filePath.toLowerCase();
  if (lower.endsWith(".html")) return "text/html; charset=utf-8";
  if (lower.endsWith(".js")) return "application/javascript; charset=utf-8";
  if (lower.endsWith(".mjs")) return "application/javascript; charset=utf-8";
  if (lower.endsWith(".css")) return "text/css; charset=utf-8";
  if (lower.endsWith(".json")) return "application/json; charset=utf-8";
  if (lower.endsWith(".svg")) return "image/svg+xml";
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".ico")) return "image/x-icon";
  return "application/octet-stream";
}

async function serveFile(path: string): Promise<Response> {
  const file = Bun.file(path);
  if (!(await file.exists())) {
    throw new HttpError(404, "File not found");
  }
  return new Response(file, {
    headers: { "Content-Type": contentTypeFor(path) },
  });
}

projectSpaRouter.get("/projects/:token/:project/video-player", async (c) => {
  const { token } = c.req.param();
  await verifyMediaToken(token);
  return serveFile(VIDEO_PLAYER_HTML);
});

projectSpaRouter.get(
  "/projects/:token/:project/static/*",
  async (c) => {
    const { token } = c.req.param();
    await verifyMediaToken(token);

    const url = new URL(c.req.url);
    const prefix = `/projects/${c.req.param("token")}/${c.req.param("project")}/static/`;
    const rest = url.pathname.startsWith(prefix)
      ? url.pathname.slice(prefix.length)
      : "";
    if (!rest) {
      throw new HttpError(404, "File not found");
    }
    const requested = normalize(join(FRONTEND_ROOT, rest));
    const rootWithSep = FRONTEND_ROOT.endsWith(sep) ? FRONTEND_ROOT : FRONTEND_ROOT + sep;
    if (!requested.startsWith(rootWithSep)) {
      throw new HttpError(403, "Invalid path");
    }
    return serveFile(requested);
  },
);

projectSpaRouter.get("/projects/:token/:project/", async (c) => {
  const { token } = c.req.param();
  await verifyMediaToken(token);
  return serveFile(INDEX_HTML);
});

projectSpaRouter.get("/projects/:token/:project/*", async (c) => {
  const { token } = c.req.param();
  await verifyMediaToken(token);
  return serveFile(INDEX_HTML);
});
