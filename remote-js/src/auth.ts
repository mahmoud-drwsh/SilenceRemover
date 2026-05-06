/**
 * Auth helpers - 1:1 port of the Python `_token_hash` / `_verify_stored_token`
 * / `_set_token_hash` / `_set_media_token` / rate-limit logic in remote/app.py.
 *
 * Tokens are never stored in plaintext (except the media token, which lives in
 * Supabase Vault for the admin dashboard to surface as a one-time copyable
 * link).
 */

import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
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

/**
 * Set the media (project) token. Stores the hash in `auth_tokens` and the
 * recoverable plaintext in Supabase Vault. Mirrors `_set_media_token`.
 */
export async function setMediaToken(token: string): Promise<void> {
  const config = loadConfig();
  const normalized = token.trim();
  if (!normalized) {
    throw new Error("Project token cannot be empty");
  }

  const sql = getDb();
  const ident = schemaIdent();
  const auth = `${ident}.auth_tokens`;

  await sql.begin(async (tx) => {
    const existingRows = await tx.unsafe<{ vault_secret_id: string | null }[]>(
      `SELECT vault_secret_id FROM ${auth} WHERE kind = 'media'`,
    );
    let vaultSecretId: string | null = existingRows[0]?.vault_secret_id ?? null;

    if (!vaultSecretId) {
      const lookup = await tx.unsafe<{ id: string }[]>(
        `SELECT id FROM vault.decrypted_secrets WHERE name = $1`,
        [config.mediaTokenVaultName],
      );
      vaultSecretId = lookup[0]?.id ?? null;
    }

    if (vaultSecretId) {
      await tx.unsafe(
        `SELECT vault.update_secret($1::uuid, $2, $3, $4)`,
        [
          vaultSecretId,
          normalized,
          config.mediaTokenVaultName,
          "Media Manager project URL token",
        ],
      );
    } else {
      const created = await tx.unsafe<{ id: string }[]>(
        `SELECT vault.create_secret($1, $2, $3) AS id`,
        [
          normalized,
          config.mediaTokenVaultName,
          "Media Manager project URL token",
        ],
      );
      vaultSecretId = created[0]?.id ?? null;
    }

    await tx.unsafe(
      `
      INSERT INTO ${auth} (kind, token_hash, vault_secret_id)
      VALUES ($1, $2, $3)
      ON CONFLICT (kind) DO UPDATE
      SET token_hash = EXCLUDED.token_hash,
          vault_secret_id = EXCLUDED.vault_secret_id,
          rotated_at = now(),
          version = ${auth}.version + 1
      `,
      ["media", tokenHash(normalized), vaultSecretId],
    );
  });
}

/**
 * Return the recoverable media token from Supabase Vault, or null when none
 * is stored yet. Used by the admin dashboard to render copyable project URLs.
 */
export async function getMediaTokenPlaintext(): Promise<string | null> {
  const sql = getDb();
  const ident = schemaIdent();
  const auth = `${ident}.auth_tokens`;
  const rows = await sql.unsafe<{ decrypted_secret: string | null }[]>(
    `
    SELECT ds.decrypted_secret
    FROM ${auth} t
    JOIN vault.decrypted_secrets ds ON ds.id = t.vault_secret_id
    WHERE t.kind = 'media'
    `,
  );
  return rows[0]?.decrypted_secret ?? null;
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
