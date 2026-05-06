import { NextResponse } from "next/server";
import { verifyAdminToken } from "@/lib/auth";
import { storageProjectSizeTotals } from "@/lib/s3";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ admin_token: string }> },
): Promise<Response> {
  try {
    const { admin_token } = await context.params;
    await verifyAdminToken(admin_token, request);

    const totals = await storageProjectSizeTotals();
    const projects = Object.entries(totals)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([project, s3_storage_bytes]) => ({ project, s3_storage_bytes }));

    return NextResponse.json({
      projects,
      total_s3_storage_bytes: Object.values(totals).reduce((a, b) => a + b, 0),
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
