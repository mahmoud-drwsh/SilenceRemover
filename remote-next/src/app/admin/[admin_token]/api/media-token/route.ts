import { NextResponse } from "next/server";
import { z } from "zod";
import { auditAdminEvent, setMediaToken, verifyAdminToken } from "@/lib/auth";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BodySchema = z.object({
  token: z.string(),
});

export async function POST(
  request: Request,
  context: { params: Promise<{ admin_token: string }> },
): Promise<Response> {
  try {
    const { admin_token } = await context.params;
    await verifyAdminToken(admin_token, request);

    const parsed = BodySchema.safeParse(await request.json());
    if (!parsed.success) {
      return NextResponse.json({ detail: parsed.error.message }, { status: 400 });
    }

    await setMediaToken(parsed.data.token);
    await auditAdminEvent("token-admin", "set_media_token", request, {
      token_length: parsed.data.token.trim().length,
    });

    return NextResponse.json({
      ok: true,
      media_token: parsed.data.token.trim(),
      persisted: true,
      persistence: "supabase-vault",
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
