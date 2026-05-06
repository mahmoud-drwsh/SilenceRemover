/**
 * Postgres metadata wrapper for the Media Manager service.
 *
 * Uses porsager/postgres with a connection pool. Tagged-template SQL keeps
 * parameter binding safe; helpers expose the schema-qualified table names so
 * we never interpolate identifiers into SQL by hand.
 */

import postgres from "postgres";
import { loadConfig } from "./config.ts";

let cachedClient: postgres.Sql | undefined;

/** Return the lazily-initialized postgres pool. */
export function getDb(): postgres.Sql {
  if (cachedClient) return cachedClient;
  const config = loadConfig();
  cachedClient = postgres(config.supabaseDatabaseUrl, {
    prepare: false,
    onnotice: () => {},
    transform: {
      undefined: null,
    },
  });
  return cachedClient;
}

/** Close the postgres pool. Useful for graceful shutdown. */
export async function closeDb(): Promise<void> {
  if (cachedClient) {
    await cachedClient.end({ timeout: 5 });
    cachedClient = undefined;
  }
}

/** Pre-quoted schema identifier (e.g. `"media_manager"`). */
export function schemaIdent(): string {
  return loadConfig().supabaseSchemaIdent;
}

/** Verify the schema and required tables exist; throws on failure. */
export async function ensureDatabaseReady(): Promise<void> {
  const sql = getDb();
  const ident = schemaIdent();
  await sql.unsafe(`SELECT 1 FROM ${ident}.files LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.auth_tokens LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.admin_audit_log LIMIT 1`);
}
