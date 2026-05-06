export const SUPABASE_DATABASE_URL = process.env.SUPABASE_DATABASE_URL ?? "";
export const SUPABASE_DB_SCHEMA =
  process.env.SUPABASE_DB_SCHEMA ?? "media_manager";
export const S3_ENDPOINT_URL = process.env.S3_ENDPOINT_URL ?? "";
export const S3_BUCKET = process.env.S3_BUCKET ?? "media-manager";
export const S3_ACCESS_KEY = process.env.S3_ACCESS_KEY ?? "";
export const S3_SECRET_KEY = process.env.S3_SECRET_KEY ?? "";
export const S3_REGION = process.env.S3_REGION ?? "eu2";
export const MAX_FILE_SIZE = 500 * 1024 * 1024;
export const MEDIA_TOKEN_VAULT_NAME = "media-manager-media-token";
export const LOGIN_RATE_LIMIT_WINDOW_SEC = 15 * 60;
export const LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 8;
