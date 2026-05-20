/**
 * Auth helpers - 1:1 port of the Python `_token_hash` / `_verify_stored_token`
 * / `_set_token_hash` / `_set_media_token` / rate-limit logic in remote/app.py.
 *
 * Tokens are never stored in plaintext. The media token is encrypted with an
 * app-held key so the admin dashboard can surface project links without
 * depending on a provider-specific vault.
 */

import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";
import { getDb, schemaIdent } from "./db.ts";
import { loadConfig } from "./config.ts";

export type TokenKind = "admin" | "media";

/** SHA-256 hex digest of the token. */
function tokenHash(token: string): string {
  return createHash("sha256").update(token, "utf-8").digest("hex");
}

/** Constant-time comparison of two hex SHA-256 digests. */
function constantTimeHexEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  try {
    return timingSafeEqual(Buffer.from(left, "hex"), Buffer.from(right, "hex"));
  } catch {
    return false;
  }
}

/** Generate a new high-entropy random media token (32 bytes -> 43 char URL-safe). */
export function generateMediaToken(): string {
  return randomBytes(32).toString("base64url");
}

/**
 * Generate a new admin token of shape `mm_admin_<48-byte URL-safe>`.
 * Matches Python `_generate_admin_token`.
 */
export function generateAdminToken(): string {
  return "mm_admin_" + randomBytes(48).toString("base64url");
}

/** Return the stored token hash for a kind, or null if unset. */
async function getStoredTokenHash(kind: TokenKind): Promise<string | null> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ token_hash: string }[]>(
    `SELECT token_hash FROM ${ident}.auth_tokens WHERE kind = $1`,
    [kind],
  );
  const row = rows[0];
  return row ? row.token_hash : null;
}

/** Verify the provided token against the stored hash for a kind. */
export async function verifyStoredToken(
  kind: TokenKind,
  token: string,
): Promise<boolean> {
  const stored = await getStoredTokenHash(kind);
  if (!stored) return false;
  return constantTimeHexEqual(stored, tokenHash(token));
}

/** Upsert a token hash for a kind. */
async function setTokenHash(kind: TokenKind, token: string): Promise<void> {
  const sql = getDb();
  const ident = schemaIdent();
  const auth = `${ident}.auth_tokens`;
  await sql.unsafe(
    `
    INSERT INTO ${auth} (kind, token_hash)
    VALUES ($1, $2)
    ON CONFLICT (kind) DO UPDATE
    SET token_hash = EXCLUDED.token_hash,
        rotated_at = now(),
        version = ${auth}.version + 1
    `,
    [kind, tokenHash(token)],
  );
}

/** Rotate the admin token; returns the new plaintext token. */
export async function rotateAdminToken(): Promise<string> {
  const newToken = generateAdminToken();
  await setTokenHash("admin", newToken);
  return newToken;
}

const MEDIA_TOKEN_CIPHER_VERSION = "v1";

/** Set the media (project) token hash and encrypted recoverable token. */
export async function setMediaToken(token: string): Promise<void> {
  const config = loadConfig();
  const normalized = token.trim();
  if (!normalized) {
    throw new Error("Project token cannot be empty");
  }

  const sql = getDb();
  const ident = schemaIdent();
  const auth = `${ident}.auth_tokens`;
  const encryptedToken = encryptSecret(normalized, config.tokenEncryptionKey);

  await sql.unsafe(
    `
    INSERT INTO ${auth} (kind, token_hash, encrypted_token)
    VALUES ($1, $2, $3)
    ON CONFLICT (kind) DO UPDATE
    SET token_hash = EXCLUDED.token_hash,
        encrypted_token = EXCLUDED.encrypted_token,
        rotated_at = now(),
        version = ${auth}.version + 1
    `,
    ["media", tokenHash(normalized), encryptedToken],
  );
}

/** Return the recoverable media token, or null when none is stored yet. */
export async function getMediaTokenPlaintext(): Promise<string | null> {
  const config = loadConfig();
  const sql = getDb();
  const ident = schemaIdent();
  const auth = `${ident}.auth_tokens`;
  const rows = await sql.unsafe<{ encrypted_token: string | null }[]>(
    `SELECT encrypted_token FROM ${auth} WHERE kind = 'media'`,
  );
  const encryptedToken = rows[0]?.encrypted_token ?? null;
  if (!encryptedToken) return null;
  return decryptSecret(encryptedToken, config.tokenEncryptionKey);
}

function encryptSecret(secret: string, key: Buffer): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const encrypted = Buffer.concat([
    cipher.update(secret, "utf8"),
    cipher.final(),
  ]);
  const tag = cipher.getAuthTag();
  return [
    MEDIA_TOKEN_CIPHER_VERSION,
    iv.toString("base64url"),
    tag.toString("base64url"),
    encrypted.toString("base64url"),
  ].join(".");
}

function decryptSecret(payload: string, key: Buffer): string {
  const [version, ivRaw, tagRaw, encryptedRaw] = payload.split(".");
  if (
    version !== MEDIA_TOKEN_CIPHER_VERSION ||
    !ivRaw ||
    !tagRaw ||
    !encryptedRaw
  ) {
    throw new Error("Unsupported encrypted token payload");
  }
  const decipher = createDecipheriv(
    "aes-256-gcm",
    key,
    Buffer.from(ivRaw, "base64url"),
  );
  decipher.setAuthTag(Buffer.from(tagRaw, "base64url"));
  return Buffer.concat([
    decipher.update(Buffer.from(encryptedRaw, "base64url")),
    decipher.final(),
  ]).toString("utf8");
}

/* -------------------------------------------------------------------------- */
/* Rate limiter                                                               */
/* -------------------------------------------------------------------------- */

interface RateLimitState {
  attempts: Map<string, number[]>;
}

const rateLimitState: RateLimitState = { attempts: new Map() };

function nowSeconds(): number {
  return performance.now() / 1000;
}

function rateLimitKey(peerIp: string, label: string): string {
  return `${peerIp}:${label.trim().toLowerCase()}`;
}

export interface RateLimitTooMany {
  retryAfterSeconds: number;
}

/**
 * Returns null when the request is allowed, or the retry-after seconds when
 * blocked. Mirrors `_check_login_rate_limit`.
 */
export function checkLoginRateLimit(
  peerIp: string,
  label: string,
): RateLimitTooMany | null {
  const config = loadConfig();
  const key = rateLimitKey(peerIp, label);
  const now = nowSeconds();
  const cutoff = now - config.loginRateLimitWindowSec;
  const recent = (rateLimitState.attempts.get(key) ?? []).filter(
    (stamp) => stamp >= cutoff,
  );

  if (recent.length >= config.loginRateLimitMaxAttempts) {
    const oldest = recent[0] ?? now;
    const retryAfter = Math.max(
      1,
      Math.floor(config.loginRateLimitWindowSec - (now - oldest)),
    );
    return { retryAfterSeconds: retryAfter };
  }

  rateLimitState.attempts.set(key, recent);
  return null;
}

/** Record a failed login attempt for the rate limiter. */
export function recordFailedLogin(peerIp: string, label: string): void {
  const config = loadConfig();
  const key = rateLimitKey(peerIp, label);
  const now = nowSeconds();
  const cutoff = now - config.loginRateLimitWindowSec;
  const recent = (rateLimitState.attempts.get(key) ?? []).filter(
    (stamp) => stamp >= cutoff,
  );
  recent.push(now);
  rateLimitState.attempts.set(key, recent);
}

/** Clear the rate-limit counter on successful login. */
export function clearLoginRateLimit(peerIp: string, label: string): void {
  rateLimitState.attempts.delete(rateLimitKey(peerIp, label));
}
