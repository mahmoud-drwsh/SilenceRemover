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
  };
  return cached;
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
