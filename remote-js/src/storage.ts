/**
 * S3-compatible object storage wrappers. Mirrors the helpers in remote/app.py
 * (`storage_object_key`, `storage_put_bytes`, `storage_delete`,
 * `storage_delete_any_extension`, `storage_project_size_totals`,
 * `storage_stream_response`, `ensure_storage_backend_ready`).
 */

import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CopyObjectCommand,
  CreateMultipartUploadCommand,
  DeleteObjectCommand,
  GetObjectCommand,
  HeadBucketCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
  UploadPartCommand,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { NodeHttpHandler } from "@smithy/node-http-handler";
import { createHash } from "node:crypto";
import { loadConfig } from "./config.ts";
import { MIME_TO_EXT } from "./mime.ts";
import type { FileType } from "./schemas.ts";

export const MULTIPART_PART_SIZE = 8 * 1024 * 1024;
export const PRESIGNED_URL_TTL_SEC = 15 * 60;

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
    requestHandler: new NodeHttpHandler({
      requestTimeout: 600_000,
    }),
  });
  return cachedClient;
}

/** Build the S3 object key matching the existing storage tree layout. */
export function storageObjectKey(
  fileType: "audio" | "video" | "original" | "subtitle",
  project: string,
  fileId: string,
  ext: string,
): string {
  return `${fileType}/${project}/${fileId}${ext}`;
}

export function remuxTemporaryObjectKey(project: string, jobId: string): string {
  return `remux/${project}/${jobId}.mp4`;
}

function sourceArtifactTemporaryObjectKey(project: string, jobId: string, leaseToken: string, kind: string): string {
  return `source-processing/${project}/${jobId}/${leaseToken}/${kind}`;
}

export async function presignSourceArtifactPut(project: string, jobId: string, leaseToken: string, kind: string, mime: string): Promise<string> {
  const config = loadConfig();
  return getSignedUrl(getS3Client(), new PutObjectCommand({ Bucket: config.s3Bucket, Key: sourceArtifactTemporaryObjectKey(project, jobId, leaseToken, kind), ContentType: mime }), { expiresIn: PRESIGNED_URL_TTL_SEC });
}

export async function sourceArtifactTemporaryHead(project: string, jobId: string, leaseToken: string, kind: string): Promise<StorageHead | null> {
  const config = loadConfig();
  try { const result = await getS3Client().send(new HeadObjectCommand({ Bucket: config.s3Bucket, Key: sourceArtifactTemporaryObjectKey(project, jobId, leaseToken, kind) })); return { size: Number(result.ContentLength ?? 0) }; } catch { return null; }
}

export async function sourceArtifactTemporarySha256(project: string, jobId: string, leaseToken: string, kind: string): Promise<string> {
  const config = loadConfig(); const result = await getS3Client().send(new GetObjectCommand({ Bucket: config.s3Bucket, Key: sourceArtifactTemporaryObjectKey(project, jobId, leaseToken, kind) }));
  const body = result.Body; if (!body || typeof (body as { transformToWebStream?: () => unknown }).transformToWebStream !== "function") throw new Error("S3 GetObject returned no body");
  const reader = (body as { transformToWebStream: () => ReadableStream<Uint8Array> }).transformToWebStream().getReader(); const hash = createHash("sha256");
  try { while (true) { const { done, value } = await reader.read(); if (done) break; hash.update(value); } } finally { reader.releaseLock(); }
  return hash.digest("hex");
}

export async function promoteSourceArtifact(project: string, jobId: string, leaseToken: string, kind: string, type: "audio" | "subtitle" | "video", id: string, ext: string, mime: string): Promise<void> {
  const config = loadConfig(); await getS3Client().send(new CopyObjectCommand({ Bucket: config.s3Bucket, CopySource: `${config.s3Bucket}/${sourceArtifactTemporaryObjectKey(project, jobId, leaseToken, kind)}`, Key: storageObjectKey(type, project, id, ext), ContentType: mime, MetadataDirective: "REPLACE" }));
}

export async function deleteSourceArtifactTemporary(project: string, jobId: string, leaseToken: string, kind: string): Promise<void> {
  const config = loadConfig(); await getS3Client().send(new DeleteObjectCommand({ Bucket: config.s3Bucket, Key: sourceArtifactTemporaryObjectKey(project, jobId, leaseToken, kind) }));
}

export async function presignTemporaryRemuxPut(project: string, jobId: string): Promise<string> {
  const config = loadConfig();
  return getSignedUrl(getS3Client(), new PutObjectCommand({
    Bucket: config.s3Bucket,
    Key: remuxTemporaryObjectKey(project, jobId),
    ContentType: "video/mp4",
  }), { expiresIn: PRESIGNED_URL_TTL_SEC });
}

export async function temporaryRemuxHead(project: string, jobId: string): Promise<StorageHead | null> {
  const config = loadConfig();
  try {
    const result = await getS3Client().send(new HeadObjectCommand({
      Bucket: config.s3Bucket, Key: remuxTemporaryObjectKey(project, jobId),
    }));
    return { size: Number(result.ContentLength ?? 0) };
  } catch {
    return null;
  }
}

export async function temporaryRemuxSha256(project: string, jobId: string): Promise<string> {
  const config = loadConfig();
  const result = await getS3Client().send(new GetObjectCommand({
    Bucket: config.s3Bucket, Key: remuxTemporaryObjectKey(project, jobId),
  }));
  const body = result.Body;
  if (!body || typeof (body as { transformToWebStream?: () => unknown }).transformToWebStream !== "function") {
    throw new Error("S3 GetObject returned no body");
  }
  const reader = (body as { transformToWebStream: () => ReadableStream<Uint8Array> }).transformToWebStream().getReader();
  const hash = createHash("sha256");
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      hash.update(value);
    }
  } finally { reader.releaseLock(); }
  return hash.digest("hex");
}

export async function promoteTemporaryRemux(project: string, jobId: string, videoId: string, ext: string): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new CopyObjectCommand({
    Bucket: config.s3Bucket,
    CopySource: `${config.s3Bucket}/${remuxTemporaryObjectKey(project, jobId)}`,
    Key: storageObjectKey("video", project, videoId, ext),
    ContentType: "video/mp4",
    MetadataDirective: "REPLACE",
  }));
}

export async function deleteTemporaryRemux(project: string, jobId: string): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new DeleteObjectCommand({
    Bucket: config.s3Bucket, Key: remuxTemporaryObjectKey(project, jobId),
  }));
}

/** HeadBucket smoke check used at startup. */
export async function ensureStorageBackendReady(): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new HeadBucketCommand({ Bucket: config.s3Bucket }));
}

/** Delete a single object from S3. Throws on failure. */
export async function storageDelete(
  fileType: "audio" | "video" | "original" | "subtitle",
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
  fileType: "audio" | "video" | "original" | "subtitle",
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
  fileType: "audio" | "video" | "original" | "subtitle",
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

export interface StorageHead {
  size: number;
}

/** HeadObject; throws (or returns null) when the object does not exist. */
export async function storageHead(
  fileType: "audio" | "video" | "original" | "subtitle",
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

/**
 * Issue a GetObject (optionally with a `Range`) and return the body as a web
 * ReadableStream. Use this for large responses where buffering in memory would
 * be impractical. Note: Bun will send the response with chunked transfer
 * encoding, dropping any Content-Length header set by the caller.
 */
export async function storageGet(
  fileType: "audio" | "video" | "original" | "subtitle",
  project: string,
  fileId: string,
  ext: string,
  byteRange: { start: number; end: number } | null,
): Promise<ReadableStream<Uint8Array>> {
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
  return (body as { transformToWebStream: () => ReadableStream<Uint8Array> }).transformToWebStream();
}

/**
 * Issue a GetObject (optionally with a `Range`) and buffer the full response
 * into a Uint8Array. Using transformToByteArray() prevents Bun from switching
 * to chunked transfer encoding, so the Content-Length header set by the caller
 * is preserved and reaches the client. Only call this when the expected body
 * size is within a safe in-memory limit.
 */
export async function storageGetBytes(
  fileType: "audio" | "video" | "original" | "subtitle",
  project: string,
  fileId: string,
  ext: string,
  byteRange: { start: number; end: number } | null,
): Promise<Uint8Array> {
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
  if (!body || typeof (body as { transformToByteArray?: () => unknown }).transformToByteArray !== "function") {
    throw new Error("S3 GetObject returned no body");
  }
  return (body as { transformToByteArray: () => Promise<Uint8Array> }).transformToByteArray();
}

/** Stream an object's SHA-256 digest without buffering the original in memory. */
export async function storageSha256(
  fileType: "audio" | "video" | "original" | "subtitle",
  project: string,
  fileId: string,
  ext: string,
): Promise<string> {
  const stream = await storageGet(fileType, project, fileId, ext, null);
  const reader = stream.getReader();
  const hash = createHash("sha256");
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      hash.update(value);
    }
  } finally {
    reader.releaseLock();
  }
  return hash.digest("hex");
}

export async function createMultipartUpload(
  fileType: FileType, project: string, fileId: string, ext: string, mime: string,
): Promise<string> {
  const config = loadConfig();
  const result = await getS3Client().send(new CreateMultipartUploadCommand({
    Bucket: config.s3Bucket, Key: storageObjectKey(fileType, project, fileId, ext), ContentType: mime,
  }));
  if (!result.UploadId) throw new Error("S3 did not return a multipart upload ID");
  return result.UploadId;
}

export async function presignUploadPart(
  fileType: FileType, project: string, fileId: string, ext: string, uploadId: string, partNumber: number,
): Promise<string> {
  const config = loadConfig();
  return getSignedUrl(getS3Client(), new UploadPartCommand({
    Bucket: config.s3Bucket, Key: storageObjectKey(fileType, project, fileId, ext), UploadId: uploadId, PartNumber: partNumber,
  }), { expiresIn: PRESIGNED_URL_TTL_SEC });
}

export async function uploadMultipartPart(
  fileType: FileType, project: string, fileId: string, ext: string, uploadId: string,
  partNumber: number, body: Uint8Array,
): Promise<string> {
  const config = loadConfig();
  const result = await getS3Client().send(new UploadPartCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey(fileType, project, fileId, ext),
    UploadId: uploadId,
    PartNumber: partNumber,
    Body: body,
  }));
  if (!result.ETag) throw new Error("S3 did not return an ETag for the uploaded part");
  return result.ETag;
}

export async function presignPutObject(
  fileType: FileType, project: string, fileId: string, ext: string, mime: string,
): Promise<string> {
  const config = loadConfig();
  return getSignedUrl(getS3Client(), new PutObjectCommand({
    Bucket: config.s3Bucket, Key: storageObjectKey(fileType, project, fileId, ext), ContentType: mime,
  }), { expiresIn: PRESIGNED_URL_TTL_SEC });
}

export async function completeMultipartUpload(
  fileType: FileType, project: string, fileId: string, ext: string, uploadId: string,
  parts: Array<{ partNumber: number; etag: string }>,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new CompleteMultipartUploadCommand({
    Bucket: config.s3Bucket, Key: storageObjectKey(fileType, project, fileId, ext), UploadId: uploadId,
    MultipartUpload: { Parts: parts.map((part) => ({ PartNumber: part.partNumber, ETag: part.etag })) },
  }));
}

export async function abortMultipartUpload(
  fileType: FileType, project: string, fileId: string, ext: string, uploadId: string,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new AbortMultipartUploadCommand({
    Bucket: config.s3Bucket, Key: storageObjectKey(fileType, project, fileId, ext), UploadId: uploadId,
  }));
}

export async function createOriginalMultipartUpload(
  project: string,
  fileId: string,
  ext: string,
  mime: string,
): Promise<string> {
  const config = loadConfig();
  const result = await getS3Client().send(new CreateMultipartUploadCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey("original", project, fileId, ext),
    ContentType: mime,
  }));
  if (!result.UploadId) throw new Error("S3 did not return a multipart upload ID");
  return result.UploadId;
}

export async function presignOriginalPart(
  project: string,
  fileId: string,
  ext: string,
  uploadId: string,
  partNumber: number,
): Promise<string> {
  const config = loadConfig();
  return getSignedUrl(getS3Client(), new UploadPartCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey("original", project, fileId, ext),
    UploadId: uploadId,
    PartNumber: partNumber,
  }), { expiresIn: 15 * 60 });
}

export async function completeOriginalMultipartUpload(
  project: string,
  fileId: string,
  ext: string,
  uploadId: string,
  parts: Array<{ partNumber: number; etag: string }>,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new CompleteMultipartUploadCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey("original", project, fileId, ext),
    UploadId: uploadId,
    MultipartUpload: { Parts: parts.map((part) => ({ PartNumber: part.partNumber, ETag: part.etag })) },
  }));
}

export async function abortOriginalMultipartUpload(
  project: string,
  fileId: string,
  ext: string,
  uploadId: string,
): Promise<void> {
  const config = loadConfig();
  await getS3Client().send(new AbortMultipartUploadCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey("original", project, fileId, ext),
    UploadId: uploadId,
  }));
}

export async function presignOriginalDownload(
  project: string,
  fileId: string,
  ext: string,
  filename: string,
): Promise<string> {
  const config = loadConfig();
  return getSignedUrl(getS3Client(), new GetObjectCommand({
    Bucket: config.s3Bucket,
    Key: storageObjectKey("original", project, fileId, ext),
    ResponseContentDisposition: `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`,
  }), { expiresIn: 5 * 60 });
}

/**
 * Aggregate exact object-byte totals per project by listing both the
 * `audio/`, `video/`, and `original/` prefixes. Mirrors
 * `storage_project_size_totals`.
 */
export async function storageProjectSizeTotals(): Promise<
  Record<string, number>
> {
  const config = loadConfig();
  const client = getS3Client();
  const totals = new Map<string, number>();

  for (const fileType of ["audio", "video", "original", "subtitle"] as const) {
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
