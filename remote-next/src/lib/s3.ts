import "server-only";

import {
  DeleteObjectCommand,
  HeadBucketCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import {
  S3_ACCESS_KEY,
  S3_BUCKET,
  S3_ENDPOINT_URL,
  S3_REGION,
  S3_SECRET_KEY,
} from "./config";
import { getFileExtension, MIME_TO_EXT } from "./mime";

let client: S3Client | null = null;

export function getS3Client(): S3Client {
  if (!S3_ENDPOINT_URL || !S3_ACCESS_KEY || !S3_SECRET_KEY) {
    throw new Error(
      "S3_ENDPOINT_URL, S3_ACCESS_KEY, and S3_SECRET_KEY must be set",
    );
  }
  if (!client) {
    client = new S3Client({
      region: S3_REGION,
      endpoint: S3_ENDPOINT_URL,
      credentials: {
        accessKeyId: S3_ACCESS_KEY,
        secretAccessKey: S3_SECRET_KEY,
      },
      forcePathStyle: true,
    });
  }
  return client;
}

export function storageObjectKey(
  fileType: string,
  project: string,
  fileId: string,
  ext: string,
): string {
  return `${fileType}/${project}/${fileId}${ext}`;
}

export async function ensureStorageBackendReady(): Promise<void> {
  await getS3Client().send(new HeadBucketCommand({ Bucket: S3_BUCKET }));
}

export async function storageDelete(
  fileType: string,
  project: string,
  fileId: string,
  ext: string,
): Promise<void> {
  await getS3Client().send(
    new DeleteObjectCommand({
      Bucket: S3_BUCKET,
      Key: storageObjectKey(fileType, project, fileId, ext),
    }),
  );
}

export async function storageDeleteAnyExtension(
  fileType: string,
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
      /* continue */
    }
  }
  return deleted;
}

export async function storagePutBytes(
  fileType: string,
  project: string,
  fileId: string,
  ext: string,
  body: Buffer,
  mime: string,
): Promise<void> {
  await getS3Client().send(
    new PutObjectCommand({
      Bucket: S3_BUCKET,
      Key: storageObjectKey(fileType, project, fileId, ext),
      Body: body,
      ContentType: mime,
    }),
  );
}

export async function storageProjectSizeTotals(): Promise<Record<string, number>> {
  const totals: Record<string, number> = {};
  const c = getS3Client();

  for (const fileType of ["audio", "video"] as const) {
    const prefix = `${fileType}/`;
    let continuationToken: string | undefined;

    while (true) {
      const page = await c.send(
        new ListObjectsV2Command({
          Bucket: S3_BUCKET,
          Prefix: prefix,
          ContinuationToken: continuationToken,
        }),
      );

      for (const obj of page.Contents ?? []) {
        const key = obj.Key ?? "";
        const parts = key.split("/", 3);
        if (parts.length < 3 || !parts[1] || key.endsWith("/")) continue;
        const proj = parts[1]!;
        totals[proj] = (totals[proj] ?? 0) + Number(obj.Size ?? 0);
      }

      if (!page.IsTruncated) break;
      continuationToken = page.NextContinuationToken;
      if (!continuationToken) break;
    }
  }

  return totals;
}

export { getFileExtension };
