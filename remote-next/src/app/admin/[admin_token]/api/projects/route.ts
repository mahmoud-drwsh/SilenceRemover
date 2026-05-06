import { NextResponse } from "next/server";
import { getMediaTokenPlaintext, verifyAdminToken } from "@/lib/auth";
import { query } from "@/lib/db";
import { toNextResponse } from "@/lib/responses";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type ProjectRow = {
  project: string;
  audio_total: string | null;
  audio_todo: string | null;
  audio_ready: string | null;
  audio_trash: string | null;
  video_total: string | null;
  total_bytes: string | null;
  last_updated: Date | string | null;
};

export async function GET(
  request: Request,
  context: { params: Promise<{ admin_token: string }> },
): Promise<Response> {
  try {
    const { admin_token } = await context.params;
    await verifyAdminToken(admin_token, request);

    const rows = await query<ProjectRow>(
      `
        SELECT 
            project,
            COUNT(CASE WHEN type='audio' THEN 1 END) as audio_total,
            SUM(CASE WHEN type='audio' AND tags LIKE '%"todo"%' THEN 1 ELSE 0 END) as audio_todo,
            SUM(CASE WHEN type='audio' AND tags LIKE '%"ready"%' THEN 1 ELSE 0 END) as audio_ready,
            SUM(CASE WHEN type='audio' AND tags LIKE '%"trash"%' THEN 1 ELSE 0 END) as audio_trash,
            COUNT(CASE WHEN type='video' THEN 1 END) as video_total,
            COALESCE(SUM(file_size), 0) as total_bytes,
            MAX(created_at) as last_updated
        FROM files 
        GROUP BY project
        ORDER BY project
        `,
    );

    const projects = rows.map((row) => ({
      project: row.project,
      audio: {
        todo: Number(row.audio_todo ?? 0),
        ready: Number(row.audio_ready ?? 0),
        trash: Number(row.audio_trash ?? 0),
        total: Number(row.audio_total ?? 0),
      },
      video: {
        total: Number(row.video_total ?? 0),
      },
      storage_bytes: Number(row.total_bytes ?? 0),
      last_updated:
        row.last_updated instanceof Date
          ? row.last_updated.toISOString()
          : row.last_updated ?? null,
    }));

    return NextResponse.json({
      media_token: await getMediaTokenPlaintext(),
      projects,
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
