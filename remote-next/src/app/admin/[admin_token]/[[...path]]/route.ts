import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { verifyAdminToken } from "@/lib/auth";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: {
    params: Promise<{ admin_token: string; path?: string[] }>;
  },
): Promise<Response> {
  try {
    const { admin_token } = await context.params;
    await verifyAdminToken(admin_token, request);
    const html = await readFile(
      join(process.cwd(), "public/mm/admin.html"),
      "utf8",
    );
    return new Response(html, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
