import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { verifyToken } from "@/lib/auth";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ token: string; project: string }> },
): Promise<Response> {
  try {
    const { token } = await context.params;
    await verifyToken(token);
    const html = await readFile(
      join(process.cwd(), "public/mm/video-player.html"),
      "utf8",
    );
    return new Response(html, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
