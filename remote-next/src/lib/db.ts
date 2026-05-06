import "server-only";

import { Pool, type QueryResultRow } from "pg";
import {
  SUPABASE_DATABASE_URL,
  SUPABASE_DB_SCHEMA,
} from "./config";

export function quoteIdent(identifier: string): string {
  if (!identifier || /^\d/.test(identifier)) {
    throw new Error(`Unsafe Postgres identifier: ${JSON.stringify(identifier)}`);
  }
  const core = identifier.replaceAll("_", "");
  if (!core.length || !/^[a-zA-Z0-9]+$/.test(core)) {
    throw new Error(`Unsafe Postgres identifier: ${JSON.stringify(identifier)}`);
  }
  return `"${identifier.replaceAll('"', '""')}"`;
}

const SUPABASE_SCHEMA_IDENT = quoteIdent(SUPABASE_DB_SCHEMA);

function normalizeSql(sql: string): string {
  let n = sql.replaceAll("FROM files", `FROM ${SUPABASE_SCHEMA_IDENT}.files`);
  n = n.replaceAll("INTO files", `INTO ${SUPABASE_SCHEMA_IDENT}.files`);
  n = n.replaceAll("UPDATE files", `UPDATE ${SUPABASE_SCHEMA_IDENT}.files`);
  n = n.replaceAll("DELETE FROM files", `DELETE FROM ${SUPABASE_SCHEMA_IDENT}.files`);
  n = n.replaceAll("tags NOT LIKE", "tags::text NOT LIKE");
  n = n.replaceAll("tags LIKE", "tags::text LIKE");
  return n;
}

function sqlToPgParams(
  sql: string,
  params: unknown[] | null | undefined,
): { text: string; values: unknown[] } {
  const normalized = normalizeSql(sql);
  const values = params ?? [];
  let idx = 0;
  const text = normalized.replace(/\?/g, () => `$${++idx}`);
  if (idx !== values.length) {
    throw new Error(
      `SQL placeholder mismatch: expected ${idx} params, got ${values.length}`,
    );
  }
  return { text, values };
}

let pool: Pool | null = null;
let bootstrapPromise: Promise<void> | null = null;

async function runBootstrap(): Promise<void> {
  if (!SUPABASE_DATABASE_URL) {
    throw new Error("SUPABASE_DATABASE_URL must be set");
  }
  const p =
    pool ??
    new Pool({
      connectionString: SUPABASE_DATABASE_URL,
    });
  pool = p;
  const schema = SUPABASE_SCHEMA_IDENT;
  const auth = authTableName();
  const audit = adminAuditTable();
  await p.query(`SELECT 1 FROM ${schema}.files LIMIT 1`);
  await p.query(`SELECT 1 FROM ${auth} LIMIT 1`);
  await p.query(`SELECT 1 FROM ${audit} LIMIT 1`);
  const { ensureStorageBackendReady } = await import("./s3");
  await ensureStorageBackendReady();
}

export async function ensureBootstrapped(): Promise<void> {
  if (!bootstrapPromise) {
    bootstrapPromise = runBootstrap();
  }
  await bootstrapPromise;
}

export function getPool(): Pool {
  if (!SUPABASE_DATABASE_URL) {
    throw new Error("SUPABASE_DATABASE_URL must be set");
  }
  if (!pool) {
    pool = new Pool({ connectionString: SUPABASE_DATABASE_URL });
  }
  return pool;
}

export function authTableName(): string {
  return `${SUPABASE_SCHEMA_IDENT}.auth_tokens`;
}

export function adminAuditTable(): string {
  return `${SUPABASE_SCHEMA_IDENT}.admin_audit_log`;
}

export function toApiScalar(value: unknown): unknown {
  if (value instanceof Date) return value.toISOString();
  if (Array.isArray(value) || (value !== null && typeof value === "object")) {
    return JSON.stringify(value);
  }
  return value;
}

export function normalizeRow<T extends QueryResultRow>(row: T): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    out[k] = toApiScalar(v);
  }
  return out;
}

export async function query<T extends QueryResultRow = QueryResultRow>(
  sql: string,
  params?: unknown[] | null,
): Promise<T[]> {
  await ensureBootstrapped();
  const { text, values } = sqlToPgParams(sql, params);
  const res = await getPool().query<T>(text, values);
  return res.rows;
}

export async function queryOne<T extends QueryResultRow = QueryResultRow>(
  sql: string,
  params?: unknown[] | null,
): Promise<T | null> {
  const rows = await query<T>(sql, params);
  return rows[0] ?? null;
}

/** Health / startup: verifies Postgres tables + S3 bucket (via bootstrap). */
export async function initDb(): Promise<void> {
  await ensureBootstrapped();
}
