/**
 * Environment configuration for the Media Manager service.
 *
 * DATABASE_URL is required. S3_ENDPOINT_URL / S3_BUCKET / S3_ACCESS_KEY /
 * S3_SECRET_KEY / S3_REGION are required, DB_SCHEMA defaults to
 * "media_manager", and PORT defaults to 8080.
 */

const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024;
const LOGIN_RATE_LIMIT_WINDOW_SEC = 15 * 60;
const LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 8;
const TOKEN_ENCRYPTION_KEY_BYTES = 32;

function readEnv(name: string): string | undefined {
  const raw = process.env[name];
  if (raw === undefined) return undefined;
  const trimmed = raw.trim();
  return trimmed === "" ? undefined : trimmed;
}

function readRequiredEnv(name: string): string {
  const value = readEnv(name);
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

/** Validates a Postgres identifier read from env/config. */
export function quoteIdent(identifier: string): string {
  if (
    !identifier ||
    !/^[A-Za-z_][A-Za-z0-9_]*$/.test(identifier)
  ) {
    throw new Error(`Unsafe Postgres identifier: ${identifier}`);
  }
  return '"' + identifier.replace(/"/g, '""') + '"';
}

export interface AppConfig {
  port: number;
  databaseUrl: string;
  dbSchema: string;
  schemaIdent: string;
  s3EndpointUrl: string;
  s3Bucket: string;
  s3AccessKey: string;
  s3SecretKey: string;
  s3Region: string;
  maxFileSizeBytes: number;
  loginRateLimitWindowSec: number;
  loginRateLimitMaxAttempts: number;
  tokenEncryptionKey: Buffer;
  /** Server processing is the default for every project. */
  sourceProcessingWorkerToken?: string;
  sourceProcessingLeaseSeconds: number;
  sourceProcessingProfile: string;
  openRouterApiKey?: string;
  openRouterBaseUrl?: string;
  openRouterTranscriptionModel: string;
  openRouterTitleModel: string;
  reviewAnalysisTimeoutMs: number;
  reviewAnalysisMaxAttempts: number;
  reviewAnalysisPublicRateLimitWindowSec: number;
  reviewAnalysisPublicRateLimitMax: number;
  reviewAnalysisPublicConcurrencyMax: number;
}

let cached: AppConfig | undefined;

/**
 * Read and validate environment configuration. Throws on missing required
 * values. Cached for the lifetime of the process.
 */
export function loadConfig(): AppConfig {
  if (cached) return cached;

  const dbSchema = readEnv("DB_SCHEMA") ?? "media_manager";
  const schemaIdent = quoteIdent(dbSchema);
  const tokenEncryptionKey = readTokenEncryptionKey();

  cached = {
    port: Number.parseInt(readEnv("PORT") ?? "8080", 10),
    databaseUrl: readEnv("DATABASE_URL") ?? missingDatabaseUrl(),
    dbSchema,
    schemaIdent,
    s3EndpointUrl: readRequiredEnv("S3_ENDPOINT_URL"),
    s3Bucket: readEnv("S3_BUCKET") ?? "media-manager",
    s3AccessKey: readRequiredEnv("S3_ACCESS_KEY"),
    s3SecretKey: readRequiredEnv("S3_SECRET_KEY"),
    s3Region: readEnv("S3_REGION") ?? "eu2",
    maxFileSizeBytes: MAX_FILE_SIZE_BYTES,
    loginRateLimitWindowSec: LOGIN_RATE_LIMIT_WINDOW_SEC,
    loginRateLimitMaxAttempts: LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    tokenEncryptionKey,
    sourceProcessingWorkerToken: readEnv("SOURCE_PROCESSING_WORKER_TOKEN"),
    sourceProcessingLeaseSeconds: readPositiveInteger("SOURCE_PROCESSING_LEASE_SECONDS", 1800),
    sourceProcessingProfile: readEnv("SOURCE_PROCESSING_PROFILE") ?? "v1",
    openRouterApiKey: readEnv("OPENROUTER_API_KEY"),
    openRouterBaseUrl: readEnv("OPENROUTER_BASE_URL"),
    openRouterTranscriptionModel: readEnv("OPENROUTER_TRANSCRIPTION_MODEL") ?? "qwen/qwen3-asr-flash-2026-02-10",
    openRouterTitleModel: readEnv("OPENROUTER_TITLE_MODEL") ?? "google/gemini-3-flash-preview",
    reviewAnalysisTimeoutMs: readPositiveInteger("REVIEW_ANALYSIS_TIMEOUT_MS", 20_000),
    reviewAnalysisMaxAttempts: readPositiveInteger("REVIEW_ANALYSIS_MAX_ATTEMPTS", 3),
    reviewAnalysisPublicRateLimitWindowSec: readPositiveInteger("REVIEW_ANALYSIS_PUBLIC_RATE_LIMIT_WINDOW_SEC", 60),
    reviewAnalysisPublicRateLimitMax: readPositiveInteger("REVIEW_ANALYSIS_PUBLIC_RATE_LIMIT_MAX", 12),
    reviewAnalysisPublicConcurrencyMax: readPositiveInteger("REVIEW_ANALYSIS_PUBLIC_CONCURRENCY_MAX", 2),
  };
  return cached;
}

function readPositiveInteger(name: string, fallback: number): number {
  const raw = readEnv(name) ?? String(fallback);
  if (!/^[1-9][0-9]*$/.test(raw)) throw new Error(`${name} must be a positive integer`);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
  return value;
}

export function isSourceProcessingEnabled(_project: string): boolean {
  return true;
}

function missingDatabaseUrl(): never {
  throw new Error("Missing required environment variable: DATABASE_URL");
}

function readTokenEncryptionKey(): Buffer {
  const raw = readRequiredEnv("TOKEN_ENCRYPTION_KEY");
  const decoded = decodeKey(raw);
  if (decoded.length !== TOKEN_ENCRYPTION_KEY_BYTES) {
    throw new Error(
      "TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes. Generate one with: openssl rand -base64 32",
    );
  }
  return decoded;
}

function decodeKey(raw: string): Buffer {
  if (/^[0-9a-fA-F]{64}$/.test(raw)) {
    return Buffer.from(raw, "hex");
  }
  return Buffer.from(raw, "base64");
}
