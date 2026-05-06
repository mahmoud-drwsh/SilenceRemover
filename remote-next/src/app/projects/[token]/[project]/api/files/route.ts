import { unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileTypeFromBuffer } from "file-type";
import { NextResponse } from "next/server";
import { verifyToken } from "@/lib/auth";
import { MAX_FILE_SIZE } from "@/lib/config";
import { FileRow, toFileResponse } from "@/lib/file-helpers";
import { query, queryOne } from "@/lib/db";
import { probeDurationSeconds } from "@/lib/duration";
import { ALLOWED_MIME, getFileExtension } from "@/lib/mime";
import { HttpError, httpException, toNextResponse } from "@/lib/responses";
import { sanitizeFileId } from "@/lib/sanitize";
import {
  storageDelete,
  storageObjectKey,
  storagePutBytes,
} from "@/lib/s3";
import {
  normalizeTitle,
  parseTags,
  TagsValidationError,
  validateAudioTags,
} from "@/lib/tags";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function GET(
  request: Request,
  context: { params: Promise<{ token: string; project: string }> },
): Promise<Response> {
  try {
    const { token, project } = await context.params;
    await verifyToken(token);

    const url = new URL(request.url);
    const type = url.searchParams.get("type") as "audio" | "video" | null;
    const tagsParam = url.searchParams.get("tags");
    const sort = (url.searchParams.get("sort") ?? "asc") as "asc" | "desc";
    const checkIdRaw = url.searchParams.get("check_id");
    const checkTitle = url.searchParams.get("check_title");
    const includeTrash = url.searchParams.get("include_trash") === "true";
    const includePending = url.searchParams.get("include_pending") === "true";

    if (checkIdRaw) {
      const checkId = sanitizeFileId(checkIdRaw);
      if (!checkId) {
        httpException(400, "Invalid check_id");
      }
      if (!type) {
        httpException(400, "Type parameter is required when using check_id");
      }
      const row = await queryOne<FileRow>(
        `SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at
               FROM files WHERE id = ? AND project = ? AND type = ?`,
        [checkId, project, type],
      );

      if (row) {
        const existingTitle = normalizeTitle(row.title);
        if (checkTitle !== null) {
          const checkTitleNormalized = normalizeTitle(checkTitle);
          const wouldOverwrite = existingTitle !== checkTitleNormalized;
          const response = {
            ...toFileResponse(row),
            exists: true,
            would_overwrite: wouldOverwrite,
            existing_title: existingTitle,
            provided_title: checkTitleNormalized,
          };
          return NextResponse.json([response]);
        }
        return NextResponse.json([toFileResponse(row)]);
      }

      return NextResponse.json([
        {
          exists: false,
          id: checkId,
          type,
          project,
        },
      ]);
    }

    const tagList = parseTags(tagsParam);
    const conditions: string[] = ["project = ?"];
    const params: unknown[] = [project];

    if (type) {
      conditions.push("type = ?");
      params.push(type);
    }

    if (tagList?.length) {
      if (tagList.includes("trash")) {
        conditions.push("tags LIKE ?");
        params.push('%"trash"%');
        for (const tag of tagList) {
          if (tag !== "trash") {
            conditions.push("tags LIKE ?");
            params.push(`%"${tag}"%`);
          }
        }
      } else {
        for (const tag of tagList) {
          conditions.push("tags LIKE ?");
          params.push(`%"${tag}"%`);
        }
      }
    } else {
      if (!includeTrash) {
        conditions.push("tags NOT LIKE ?");
        params.push('%"trash"%');
      }
      if (!includePending && !tagList?.includes("pending")) {
        conditions.push("tags NOT LIKE ?");
        params.push('%"pending"%');
      }
    }

    const whereClause = conditions.join(" AND ");
    const sortDirection = sort === "asc" ? "ASC" : "DESC";

    const rows = await query<FileRow>(
      `
        SELECT id, project, type, title, tags, duration, file_size, mime_type, created_at
        FROM files
        WHERE ${whereClause}
        ORDER BY id ${sortDirection}
        `,
      params,
    );

    return NextResponse.json(rows.map(toFileResponse));
  } catch (err) {
    if (err instanceof HttpError) {
      return NextResponse.json(
        { detail: err.message },
        { status: err.status, headers: err.headers },
      );
    }
    console.error(err);
    return NextResponse.json({ detail: "Internal Server Error" }, { status: 500 });
  }
}

export async function POST(
  request: Request,
  context: { params: Promise<{ token: string; project: string }> },
): Promise<Response> {
  let tempPath: string | null = null;
  try {
    const { token, project } = await context.params;
    await verifyToken(token);

    const form = await request.formData();
    const idRaw = String(form.get("id") ?? "");
    let id = sanitizeFileId(idRaw);
    if (!id) {
      httpException(400, "Invalid file ID");
    }

    const title = String(form.get("title") ?? "");
    const type = String(form.get("type") ?? "") as "audio" | "video";
    if (type !== "audio" && type !== "video") {
      httpException(400, "Invalid type");
    }

    const tagsRaw = String(form.get("tags") ?? "[]");
    const file = form.get("file");
    if (!file || !(file instanceof File)) {
      httpException(400, "Missing file");
    }

    let overwritten = false;

    const existing = await queryOne<FileRow>(
      "SELECT id, title, mime_type, file_size, duration FROM files WHERE id = ? AND project = ? AND type = ?",
      [id, project, type],
    );

    if (existing) {
      if (type === "audio") {
        httpException(409, `Audio file with id '${id}' already exists`);
      }
      const oldTitle = normalizeTitle(existing.title);
      const newTitle = normalizeTitle(title);
      if (oldTitle === newTitle) {
        httpException(409, "Video with same title already exists");
      }
      console.info(
        `[OVERWRITE] Video '${id}': title changed from '${oldTitle}' to '${newTitle}'`,
      );
      const oldExt = getFileExtension(existing.mime_type);
      try {
        await storageDelete(type, project, id, oldExt);
        console.info(
          `[OVERWRITE] Deleted old stored object: ${storageObjectKey(type, project, id, oldExt)}`,
        );
      } catch (e) {
        console.warn(`[OVERWRITE WARNING] Failed to delete old stored object ${id}${oldExt}:`, e);
      }
      await query("DELETE FROM files WHERE id = ? AND project = ? AND type = ?", [
        id,
        project,
        type,
      ]);
      overwritten = true;
    }

    let tagList: string[];
    try {
      const parsed = JSON.parse(tagsRaw) as unknown;
      if (!Array.isArray(parsed)) {
        throw new Error("Tags must be an array");
      }
      tagList = parsed.map((t) => String(t));
    } catch (e) {
      httpException(400, `Invalid tags format: ${e}`);
    }

    if (type === "audio") {
      try {
        tagList = validateAudioTags(tagList);
      } catch (e) {
        if (e instanceof TagsValidationError) {
          httpException(400, e.message);
        }
        throw e;
      }
    }

    if (!tagList.length) {
      tagList = ["all"];
    }

    const buf = Buffer.from(await file.arrayBuffer());
    if (buf.length > MAX_FILE_SIZE) {
      httpException(413, `File too large (max ${MAX_FILE_SIZE} bytes)`);
    }

    tempPath = join(tmpdir(), `media-manager-${id}-${Date.now()}`);
    await writeFile(tempPath, buf);

    const ft = await fileTypeFromBuffer(buf);
    const mime = ft?.mime ?? "";
    if (!ALLOWED_MIME.has(mime)) {
      httpException(400, `Invalid file type: ${mime || "unknown"}`);
    }

    const ext = getFileExtension(mime);
    const duration = await probeDurationSeconds(tempPath);

    await storagePutBytes(type, project, id, ext, buf, mime);

    await query(
      `
        INSERT INTO files (id, project, type, title, tags, duration, file_size, mime_type)
        VALUES (?, ?, ?, ?, ?::jsonb, ?, ?, ?)
        `,
      [id, project, type, title, JSON.stringify(tagList), duration, buf.length, mime],
    );

    return NextResponse.json({
      ok: true,
      id,
      type,
      overwritten,
    });
  } catch (err) {
    return toNextResponse(err);
  } finally {
    if (tempPath) {
      try {
        await unlink(tempPath);
      } catch {
        /* ignore */
      }
    }
  }
}
