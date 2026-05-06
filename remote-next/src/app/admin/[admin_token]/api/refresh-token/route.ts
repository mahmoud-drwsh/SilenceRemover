import { NextResponse } from "next/server";
import { auditAdminEvent, rotateAdminToken, verifyAdminToken } from "@/lib/auth";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ admin_token: string }> },
): Promise<Response> {
  try {
    const { admin_token } = await context.params;
    await verifyAdminToken(admin_token, request);
    const newAdminToken = await rotateAdminToken();
    await auditAdminEvent("token-admin", "refresh_admin_token", request);
    return NextResponse.json({
      ok: true,
      admin_token: newAdminToken,
      admin_url: `/admin/${newAdminToken}/`,
      persisted: true,
      persistence: "supabase",
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
