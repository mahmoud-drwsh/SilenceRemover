import { NextResponse } from "next/server";
import { z } from "zod";
import { verifyToken } from "@/lib/auth";
import { query, queryOne } from "@/lib/db";
import { httpException, toNextResponse } from "@/lib/responses";
import { sanitizeFileId } from "@/lib/sanitize";
import {
  getFileExtension,
  storageDelete,
  storageDeleteAnyExtension,
} from "@/lib/s3";
import {
  parseTagsJson,
  TagsValidationError,
  validateAudioTags,
} from "@/lib/tags";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const UpdateSchema = z.object({
  tags: z.array(z.string()),
  title: z.string().nullable().optional(),
});

export async function PUT(
  request: Request,
  context: {
    params: Promise<{ token: string; project: string; id: string }>;
  },
): Promise<Response> {
  try {
    const { token, project, id: rawId } = await context.params;
    await verifyToken(token);

    const url = new URL(request.url);
    const type = url.searchParams.get("type") as "audio" | "video" | null;
    if (type !== "audio" && type !== "video") {
      httpException(
        400,
        "File type (audio or video) is required for safety via query param",
      );
    }

    const id = sanitizeFileId(decodeURIComponent(rawId));
    if (!id) {
      httpException(400, "Invalid file ID");
    }

    const parsed = UpdateSchema.safeParse(await request.json());
    if (!parsed.success) {
      httpException(400, parsed.error.message);
    }
    const { tags: tagsIn, title } = parsed.data;

    const row = await queryOne<{ type: string }>(
      "SELECT type FROM files WHERE id = ? AND project = ? AND type = ?",
      [id, project, type],
    );

    if (!row) {
      httpException(404, `File '${id}' of type '${type}' not found`);
    }

    let tags = tagsIn;
    if (row.type === "audio") {
      try {
        tags = validateAudioTags(tags);
      } catch (e) {
        if (e instanceof TagsValidationError) {
          httpException(400, e.message);
        }
        throw e;
      }
    }

    if (!tags.length) {
      tags = ["all"];
    }

    if (title !== undefined && title !== null) {
      await query(
        "UPDATE files SET tags = ?::jsonb, title = ? WHERE id = ? AND project = ? AND type = ?",
        [JSON.stringify(tags), title, id, project, row.type],
      );
    } else {
      await query(
        "UPDATE files SET tags = ?::jsonb WHERE id = ? AND project = ? AND type = ?",
        [JSON.stringify(tags), id, project, row.type],
      );
    }

    return NextResponse.json({
      ok: true,
      id,
      tags,
      title: parsed.data.title ?? null,
    });
  } catch (err) {
    return toNextResponse(err);
  }
}

export async function DELETE(
  request: Request,
  context: {
    params: Promise<{ token: string; project: string; id: string }>;
  },
): Promise<Response> {
  try {
    const { token, project, id: rawId } = await context.params;
    await verifyToken(token);

    const url = new URL(request.url);
    const type = url.searchParams.get("type") as "audio" | "video" | null;
    if (type !== "audio" && type !== "video") {
      httpException(
        400,
        "File type (audio or video) is required for safety via query param",
      );
    }

    const id = sanitizeFileId(decodeURIComponent(rawId));
    if (!id) {
      httpException(400, "Invalid file ID");
    }

    const row = await queryOne<{ type: string; tags: unknown; mime_type: string }>(
      "SELECT type, tags, mime_type FROM files WHERE id = ? AND project = ? AND type = ?",
      [id, project, type],
    );

    if (!row) {
      httpException(404, `File '${id}' of type '${type}' not found`);
    }

    const tags = parseTagsJson(row.tags);
    if (!tags.includes("trash")) {
      httpException(
        400,
        "Only trashed files can be deleted. Add 'trash' tag first.",
      );
    }

    const fileType = row.type;
    const ext = getFileExtension(row.mime_type);
    try {
      await storageDelete(fileType, project, id, ext);
    } catch {
      await storageDeleteAnyExtension(fileType, project, id);
    }

    await query("DELETE FROM files WHERE id = ? AND project = ? AND type = ?", [
      id,
      project,
      fileType,
    ]);

    return NextResponse.json({ ok: true, id, deleted: true });
  } catch (err) {
    return toNextResponse(err);
  }
}
