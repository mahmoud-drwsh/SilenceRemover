import { NextResponse } from "next/server";
import { initDb } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    await initDb();
    return NextResponse.json({ ok: true });
  } catch (err) {
    console.error("[healthz]", err);
    return NextResponse.json({ ok: false }, { status: 503 });
  }
}
