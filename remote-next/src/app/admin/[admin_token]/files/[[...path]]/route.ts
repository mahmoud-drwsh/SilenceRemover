import { NextResponse } from "next/server";
import { verifyAdminToken } from "@/lib/auth";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function removedBrowser(
  request: Request,
  context: { params: Promise<{ admin_token: string }> },
): Promise<Response> {
  try {
    const { admin_token } = await context.params;
    await verifyAdminToken(admin_token, request);
    return NextResponse.json(
      { detail: "Admin File Browser has been removed" },
      { status: 404 },
    );
  } catch (err) {
    return toNextResponse(err);
  }
}

export const GET = removedBrowser;
export const POST = removedBrowser;
export const PUT = removedBrowser;
export const PATCH = removedBrowser;
export const DELETE = removedBrowser;
export const HEAD = removedBrowser;
export const OPTIONS = removedBrowser;
