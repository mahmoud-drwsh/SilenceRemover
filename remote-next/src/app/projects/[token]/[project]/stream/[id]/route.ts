import { Readable } from "node:stream";
import { GetObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3";
import { verifyToken } from "@/lib/auth";
import { S3_BUCKET } from "@/lib/config";
import { queryOne } from "@/lib/db";
import { FileRow } from "@/lib/file-helpers";
import { MIME_TO_EXT } from "@/lib/mime";
import { parseRangeHeader } from "@/lib/range";
import { httpException, toNextResponse } from "@/lib/responses";
import { sanitizeFilename, sanitizeFileId } from "@/lib/sanitize";
import { getS3Client, storageObjectKey } from "@/lib/s3";
import { parseTagsJson } from "@/lib/tags";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function awsBodyToWeb(body: unknown): ReadableStream<Uint8Array> {
  const r = body as Readable | undefined;
  if (!r || typeof (r as Readable).read !== "function") {
    return new ReadableStream({
      start(c) {
        c.close();
      },
    });
  }
  return Readable.toWeb(r) as ReadableStream<Uint8Array>;
}

export async function GET(
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

    let decodedId = decodeURIComponent(rawId);
    decodedId = sanitizeFileId(decodedId);

    const row = await queryOne<FileRow>(
      "SELECT type, mime_type, tags, title FROM files WHERE id = ? AND project = ? AND type = ?",
      [decodedId, project, type],
    );

    if (!row) {
      httpException(404, `File '${decodedId}' not found`);
    }

    const tags = parseTagsJson(row.tags);
    if (tags.includes("trash")) {
      httpException(404, "File is in trash");
    }

    const fileType = row.type;
    const ext = MIME_TO_EXT[row.mime_type] ?? ".bin";
    const key = storageObjectKey(fileType, project, decodedId, ext);

    const client = getS3Client();
    let head;
    try {
      head = await client.send(
        new HeadObjectCommand({ Bucket: S3_BUCKET, Key: key }),
      );
    } catch {
      httpException(404, `File content not found: ${decodedId}${ext}`);
    }
    const size = Number(head.ContentLength ?? 0);

    const rangeHdr = request.headers.get("range");
    const byteRange = parseRangeHeader(rangeHdr, size);

    const downloadTitle = row.title ?? "";
    const safeTitle = sanitizeFilename(downloadTitle);
    const downloadFilename = safeTitle
      ? `${safeTitle}${ext}`
      : `${decodedId}${ext}`;

    const headers: Record<string, string> = {
      "Accept-Ranges": "bytes",
      "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(downloadFilename)}`,
    };

    let status: 200 | 206 = 200;
    let rangeArg: string | undefined;

    if (byteRange) {
      const [start, end] = byteRange;
      rangeArg = `bytes=${start}-${end}`;
      headers["Content-Range"] = `bytes ${start}-${end}/${size}`;
      headers["Content-Length"] = String(end - start + 1);
      status = 206;
    } else {
      headers["Content-Length"] = String(size);
    }

    const obj = await client.send(
      new GetObjectCommand({
        Bucket: S3_BUCKET,
        Key: key,
        ...(rangeArg ? { Range: rangeArg } : {}),
      }),
    );

    const stream = awsBodyToWeb(obj.Body);

    return new Response(stream, {
      status,
      headers: {
        ...headers,
        "Content-Type": row.mime_type,
      },
    });
  } catch (err) {
    return toNextResponse(err);
  }
}
