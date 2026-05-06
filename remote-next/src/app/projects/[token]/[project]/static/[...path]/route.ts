import { readFile } from "node:fs/promises";
import { join, relative, resolve } from "node:path";
import { NextResponse } from "next/server";
import { verifyToken } from "@/lib/auth";
import { httpException, toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: {
    params: Promise<{ token: string; project: string; path: string[] }>;
  },
): Promise<Response> {
  try {
    const { token, path: segments } = await context.params;
    await verifyToken(token);

    const base = resolve(join(process.cwd(), "public/mm/static"));
    const requested = resolve(base, ...segments);
    const rel = relative(base, requested);
    if (rel.startsWith("..")) {
      httpException(403, "Invalid path");
    }

    const buf = await readFile(requested);
    const ext = requested.split(".").pop()?.toLowerCase();
    const ct =
      ext === "js"
        ? "application/javascript; charset=utf-8"
        : ext === "css"
          ? "text/css; charset=utf-8"
          : ext === "json"
            ? "application/json; charset=utf-8"
            : "application/octet-stream";

    return new Response(buf, {
      headers: { "Content-Type": ct },
    });
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return NextResponse.json({ detail: "File not found" }, { status: 404 });
    }
    return toNextResponse(err);
  }
}
