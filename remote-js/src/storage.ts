/**
 * S3-compatible object storage wrappers. Mirrors the helpers in remote/app.py
 * (`storage_object_key`, `storage_put_bytes`, `storage_delete`,
 * `storage_delete_any_extension`, `storage_project_size_totals`,
 * `storage_stream_response`, `ensure_storage_backend_ready`).
 */

import {
  DeleteObjectCommand,
  GetObjectCommand,
  HeadBucketCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { createReadStream } from "node:fs";
import { loadConfig } from "./config.ts";
import { MIME_TO_EXT } from "./mime.ts";

let cachedClient: S3Client | undefined;

/** Singleton S3 client configured against the project's S3-compatible endpoint. */
export function getS3Client(): S3Client {
  if (cachedClient) return cachedClient;
  const config = loadConfig();
  cachedClient = new S3Client({
    endpoint: config.s3EndpointUrl,
    region: config.s3Region,
    forcePathStyle: true,
    credentials: {
      accessKeyId: config.s3AccessKey,
      secretAccessKey: config.s3SecretKey,
    },
  });
  return cachedClient;
}

/** Build the S3 object key matching the existing storage tree layout. */
export function storageObjectKey(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
): string {
  return `${fileType}/${project}/${fileId}${ext}`;
}

/** HeadBucket smoke check used at startup. */
export async function ensureStorageBackendReady(): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new HeadBucketCommand({ Bucket: config.s3Bucket }));
}

/** Delete a single object from S3. Throws on failure. */
export async function storageDelete(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(
    new DeleteObjectCommand({
      Bucket: config.s3Bucket,
      Key: storageObjectKey(fileType, project, fileId, ext),
    }),
  );
}

/**
 * Best-effort delete across every known extension. Mirrors
 * `storage_delete_any_extension` - useful for legacy rows whose stored MIME
 * may imply the wrong extension. Returns true if any delete succeeded.
 */
export async function storageDeleteAnyExtension(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
): Promise<boolean> {
  const exts = new Set(Object.values(MIME_TO_EXT));
  let deleted = false;
  for (const ext of exts) {
    try {
      await storageDelete(fileType, project, fileId, ext);
      deleted = true;
    } catch {
      // Continue - we want every extension attempted.
    }
  }
  return deleted;
}

/** Upload bytes to S3. Throws on failure. */
export async function storagePutBytes(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
  body: Uint8Array,
  mime: string,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(
    new PutObjectCommand({
      Bucket: config.s3Bucket,
      Key: storageObjectKey(fileType, project, fileId, ext),
      Body: body,
      ContentType: mime,
    }),
  );
}

/** Upload a local file stream to S3 without buffering the whole object in memory. */
export async function storagePutFile(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
  filePath: string,
  fileSize: number,
  mime: string,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(
    new PutObjectCommand({
      Bucket: config.s3Bucket,
      Key: storageObjectKey(fileType, project, fileId, ext),
      Body: createReadStream(filePath),
      ContentLength: fileSize,
      ContentType: mime,
    }),
  );
}

export interface StorageHead {
  size: number;
}

/** HeadObject; throws (or returns null) when the object does not exist. */
export async function storageHead(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
): Promise<StorageHead | null> {
  const config = loadConfig();
  try {
    const result = await getS3Client().send(
      new HeadObjectCommand({
        Bucket: config.s3Bucket,
        Key: storageObjectKey(fileType, project, fileId, ext),
      }),
    );
    return { size: Number(result.ContentLength ?? 0) };
  } catch {
    return null;
  }
}

export interface StorageRangeResult {
  body: ReadableStream<Uint8Array>;
  size: number;
  byteRange: { start: number; end: number } | null;
}

/**
 * Issue a GetObject (optionally with a `Range`). The caller is responsible
 * for forwarding the response stream and any headers.
 */
export async function storageGet(
  fileType: "audio" | "video",
  project: string,
  fileId: string,
  ext: string,
  byteRange: { start: number; end: number } | null,
  totalSize: number,
): Promise<StorageRangeResult> {
  const config = loadConfig();
  const command = new GetObjectCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey(fileType, project, fileId, ext),
    ...(byteRange
      ? { Range: `bytes=${byteRange.start}-${byteRange.end}` }
      : {}),
  });
  const result = await getS3Client().send(command);
  const body = result.Body;
  if (!body || typeof (body as { transformToWebStream?: () => unknown }).transformToWebStream !== "function") {
    throw new Error("S3 GetObject returned no body");
  }
  return {
    body: (body as { transformToWebStream: () => ReadableStream<Uint8Array> }).transformToWebStream(),
    size: totalSize,
    byteRange,
  };
}

/**
 * Aggregate exact object-byte totals per project by listing both the
 * `audio/` and `video/` prefixes. Mirrors `storage_project_size_totals`.
 */
export async function storageProjectSizeTotals(): Promise<
  Record<string, number>
> {
  const config = loadConfig();
  const client = getS3Client();
  const totals = new Map<string, number>();

  for (const fileType of ["audio", "video"] as const) {
    const prefix = `${fileType}/`;
    let continuationToken: string | undefined;
    while (true) {
      const page = await client.send(
        new ListObjectsV2Command({
          Bucket: config.s3Bucket,
          Prefix: prefix,
          ContinuationToken: continuationToken,
        }),
      );
      for (const obj of page.Contents ?? []) {
        const key = obj.Key ?? "";
        if (!key) continue;
        const parts = key.split("/");
        if (parts.length < 3) continue;
        const project = parts[1];
        if (!project) continue;
        if (key.endsWith("/")) continue;
        const size = Number(obj.Size ?? 0);
        totals.set(project, (totals.get(project) ?? 0) + (Number.isFinite(size) ? size : 0));
      }
      if (!page.IsTruncated) break;
      continuationToken = page.NextContinuationToken;
      if (!continuationToken) break;
    }
  }

  const result: Record<string, number> = {};
  for (const [project, size] of [...totals.entries()].sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    result[project] = size;
  }
  return result;
}
