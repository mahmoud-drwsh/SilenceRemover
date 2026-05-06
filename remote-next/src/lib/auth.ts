import "server-only";

import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import {
  LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
  LOGIN_RATE_LIMIT_WINDOW_SEC,
  MEDIA_TOKEN_VAULT_NAME,
} from "./config";
import { adminAuditTable, authTableName, query, queryOne } from "./db";
import { httpException } from "./responses";

const loginAttempts = new Map<string, number[]>();

function tokenHash(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export function generateAdminToken(): string {
  return `mm_admin_${randomBytes(48).toString("base64url")}`;
}

function safeCompareHex(a: string, b: string): boolean {
  try {
    const ba = Buffer.from(a, "hex");
    const bb = Buffer.from(b, "hex");
    if (ba.length !== bb.length) return false;
    return timingSafeEqual(ba, bb);
  } catch {
    return false;
  }
}

async function getTokenHash(kind: string): Promise<string | null> {
  const row = await queryOne<{ token_hash: string }>(
    `SELECT token_hash FROM ${authTableName()} WHERE kind = ?`,
    [kind],
  );
  return row?.token_hash ?? null;
}

async function verifyStoredToken(kind: string, token: string): Promise<boolean> {
  const stored = await getTokenHash(kind);
  if (!stored) return false;
  return safeCompareHex(stored, tokenHash(token));
}

export async function setTokenHash(kind: string, token: string): Promise<void> {
  await query(
    `
            INSERT INTO ${authTableName()} AS t (kind, token_hash)
            VALUES (?, ?)
            ON CONFLICT (kind) DO UPDATE
            SET token_hash = EXCLUDED.token_hash,
                rotated_at = now(),
                version = t.version + 1
            `,
    [kind, tokenHash(token)],
  );
}

export async function rotateAdminToken(): Promise<string> {
  const newToken = generateAdminToken();
  await setTokenHash("admin", newToken);
  return newToken;
}

export async function getMediaTokenPlaintext(): Promise<string | null> {
  const row = await queryOne<{ decrypted_secret: string }>(
    `
            SELECT ds.decrypted_secret
            FROM ${authTableName()} t
            JOIN vault.decrypted_secrets ds ON ds.id = t.vault_secret_id
            WHERE t.kind = 'media'
            `,
  );
  return row?.decrypted_secret ?? null;
}

export async function setMediaToken(token: string): Promise<void> {
  const normalized = token.trim();
  if (!normalized) {
    httpException(400, "Project token cannot be empty");
  }

  let row = await queryOne<{ vault_secret_id: string | null }>(
    `SELECT vault_secret_id FROM ${authTableName()} WHERE kind = 'media'`,
  );
  let vaultSecretId = row?.vault_secret_id ?? null;

  if (!vaultSecretId) {
    const existing = await queryOne<{ id: string }>(
      `SELECT id FROM vault.decrypted_secrets WHERE name = ?`,
      [MEDIA_TOKEN_VAULT_NAME],
    );
    vaultSecretId = existing?.id ?? null;
  }

  if (vaultSecretId) {
    await query(`SELECT vault.update_secret(?::uuid, ?, ?, ?)`, [
      vaultSecretId,
      normalized,
      MEDIA_TOKEN_VAULT_NAME,
      "Media Manager project URL token",
    ]);
  } else {
    const created = await queryOne<{ id: string }>(
      `SELECT vault.create_secret(?, ?, ?) AS id`,
      [normalized, MEDIA_TOKEN_VAULT_NAME, "Media Manager project URL token"],
    );
    vaultSecretId = created?.id ?? null;
    if (!vaultSecretId) {
      throw new Error("vault.create_secret returned no id");
    }
  }

  await query(
    `
            INSERT INTO ${authTableName()} AS t (kind, token_hash, vault_secret_id)
            VALUES (?, ?, ?)
            ON CONFLICT (kind) DO UPDATE
            SET token_hash = EXCLUDED.token_hash,
                vault_secret_id = EXCLUDED.vault_secret_id,
                rotated_at = now(),
                version = t.version + 1
            `,
    ["media", tokenHash(normalized), vaultSecretId],
  );
}

function clientIp(request: Request): string {
  return request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
}

function rateLimitKey(request: Request, email: string): string {
  return `${clientIp(request)}:${email.trim().toLowerCase()}`;
}

function checkLoginRateLimit(request: Request, email: string): void {
  const key = rateLimitKey(request, email);
  const now = performance.now() / 1000;
  const cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SEC;
  const recent = (loginAttempts.get(key) ?? []).filter((s) => s >= cutoff);
  if (recent.length >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS) {
    const retryAfter = Math.max(
      1,
      Math.floor(LOGIN_RATE_LIMIT_WINDOW_SEC - (now - recent[0]!)),
    );
    httpException(429, "Too many admin login attempts. Try again later.", {
      "Retry-After": String(retryAfter),
    });
  }
  loginAttempts.set(key, recent);
}

function recordFailedLogin(request: Request, email: string): void {
  const key = rateLimitKey(request, email);
  const now = performance.now() / 1000;
  const cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SEC;
  const recent = (loginAttempts.get(key) ?? []).filter((s) => s >= cutoff);
  recent.push(now);
  loginAttempts.set(key, recent);
}

function clearLoginRateLimit(request: Request, email: string): void {
  loginAttempts.delete(rateLimitKey(request, email));
}

export async function auditAdminEvent(
  email: string,
  action: string,
  request: Request,
  details: Record<string, unknown> | null = null,
): Promise<void> {
  try {
    await query(
      `
            INSERT INTO ${adminAuditTable()}
                (email, action, ip_address, user_agent, details)
            VALUES (?, ?, ?, ?, ?::jsonb)
            `,
      [
        email,
        action,
        clientIp(request),
        request.headers.get("user-agent") ?? "",
        JSON.stringify(details ?? {}),
      ],
    );
  } catch (exc) {
    console.warn(
      `[ADMIN AUDIT WARNING] Failed to write audit event ${JSON.stringify(action)}:`,
      exc,
    );
  }
}

export async function verifyToken(token: string): Promise<void> {
  if (!(await verifyStoredToken("media", token))) {
    httpException(401, "Invalid token");
  }
}

export async function verifyAdminToken(
  adminToken: string,
  request: Request | null,
): Promise<void> {
  if (request) {
    checkLoginRateLimit(request, "admin-token");
  }
  if (await verifyStoredToken("admin", adminToken)) {
    if (request) clearLoginRateLimit(request, "admin-token");
    return;
  }
  if (request) recordFailedLogin(request, "admin-token");
  httpException(401, "Invalid admin token");
}
