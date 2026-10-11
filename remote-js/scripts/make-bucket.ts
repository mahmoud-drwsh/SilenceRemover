/**
 * Make the S3 bucket for the isolated Compose stack (test use only). The
 * Chainguard MinIO override runs this in place of `mc mb`, because the
 * Chainguard client image has no shell. Usage: `node scripts/make-bucket.ts`.
 * It reads the same S3_* variables as the app.
 */
import { CreateBucketCommand } from "@aws-sdk/client-s3";
import { loadConfig } from "../src/server/config.ts";
import { getS3Client } from "../src/server/storage.ts";

const bucket = loadConfig().s3Bucket;
try {
  await getS3Client().send(new CreateBucketCommand({ Bucket: bucket }));
} catch (error) {
  if (!["BucketAlreadyOwnedByYou", "BucketAlreadyExists"].includes((error as Error).name)) throw error;
}
console.log(`bucket ${bucket} is ready`);
