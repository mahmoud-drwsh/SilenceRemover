import { createHash, randomBytes } from "node:crypto";
import { getDb, schemaIdent } from "./db.ts";
import { HttpError } from "./schemas.ts";

export interface PublicShareLink {
  project: string;
  created_at: string | Date;
  revoked_at: string | Date | null;
}

function hashToken(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export async function createPublicShareLink(project: string): Promise<string> {
  const token = `share_${randomBytes(32).toString("base64url")}`;
  const sql = getDb();
  const ident = schemaIdent();
  await sql.unsafe(
    `INSERT INTO ${ident}.public_share_links (token_hash, project) VALUES ($1, $2)`,
    [hashToken(token), project],
  );
  return token;
}

export async function listPublicShareLinks(project?: string): Promise<PublicShareLink[]> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = project
    ? await sql.unsafe<PublicShareLink[]>(
        `SELECT project, created_at, revoked_at FROM ${ident}.public_share_links WHERE project = $1 ORDER BY created_at DESC`,
        [project],
      )
    : await sql.unsafe<PublicShareLink[]>(
        `SELECT project, created_at, revoked_at FROM ${ident}.public_share_links ORDER BY created_at DESC`,
      );
  return rows.map((row) => ({
    project: row.project,
    created_at: row.created_at instanceof Date ? row.created_at.toISOString() : String(row.created_at),
    revoked_at: row.revoked_at ? (row.revoked_at instanceof Date ? row.revoked_at.toISOString() : String(row.revoked_at)) : null,
  }));
}

export async function revokePublicShareLink(token: string): Promise<void> {
  const sql = getDb();
  const ident = schemaIdent();
  const result = await sql.unsafe(
    `UPDATE ${ident}.public_share_links SET revoked_at = now() WHERE token_hash = $1 AND revoked_at IS NULL`,
    [hashToken(token)],
  );
  if (result.count === 0) throw new HttpError(404, "Share link not found or already revoked");
}

export async function verifyPublicShareLink(token: string): Promise<string> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ project: string }[]>(
    `SELECT project FROM ${ident}.public_share_links WHERE token_hash = $1 AND revoked_at IS NULL`,
    [hashToken(token)],
  );
  const row = rows[0];
  if (!row) throw new HttpError(404, "This share link is no longer available");
  return row.project;
}
