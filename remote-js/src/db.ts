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
  cachedClient = postgres(config.databaseUrl, {
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
  return loadConfig().schemaIdent;
}

/** Verify the schema and required tables exist; throws on failure. */
export async function ensureDatabaseReady(): Promise<void> {
  const sql = getDb();
  const schemaName = loadConfig().dbSchema;
  const ident = schemaIdent();
  await sql`CREATE SCHEMA IF NOT EXISTS ${sql(schemaName)}`;
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.files (
      id text NOT NULL,
      project text NOT NULL,
      type text NOT NULL CHECK (type IN ('audio', 'video', 'original', 'subtitle')),
      title text,
      tags jsonb NOT NULL DEFAULT '[]'::jsonb,
      duration double precision NOT NULL DEFAULT 0,
      file_size bigint NOT NULL DEFAULT 0,
      mime_type text NOT NULL,
      source_id text,
      original_filename text,
      checksum_sha256 text,
      designer_of_id text,
      media_variant text,
      review_status text,
      visibility text,
      publication_status text,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (id, project, type)
    )
  `);
  await sql.unsafe(`ALTER TABLE ${ident}.files DROP CONSTRAINT IF EXISTS files_type_check`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD CONSTRAINT files_type_check CHECK (type IN ('audio', 'video', 'original', 'subtitle'))`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS source_id text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ALTER COLUMN duration TYPE double precision USING duration::double precision`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS original_filename text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS checksum_sha256 text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS designer_of_id text`);
  // These fields are deliberately nullable during the non-destructive
  // migration. Legacy rows retain their tags unchanged and are interpreted
  // by the read-side compatibility mapping until the rehearsed backfill runs.
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS media_variant text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS review_status text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS visibility text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD COLUMN IF NOT EXISTS publication_status text`);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS files_project_type_idx ON ${ident}.files (project, type)`);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS files_tags_gin_idx ON ${ident}.files USING gin (tags)`);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS files_project_source_idx ON ${ident}.files (project, source_id)`);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS files_project_designer_of_idx ON ${ident}.files (project, designer_of_id)`);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS files_project_variant_idx ON ${ident}.files (project, media_variant)`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.upload_sessions (
      id text PRIMARY KEY,
      project text NOT NULL,
      file_id text NOT NULL,
      type text NOT NULL CHECK (type IN ('audio', 'video', 'original', 'subtitle')),
      mime_type text NOT NULL,
      file_size bigint NOT NULL,
      checksum_sha256 text NOT NULL,
      title text NOT NULL DEFAULT '',
      tags jsonb NOT NULL DEFAULT '[]'::jsonb,
      source_id text,
      original_filename text,
      upload_id text,
      designer_of_id text,
      media_variant text,
      review_status text,
      visibility text,
      publication_status text,
      expires_at timestamptz NOT NULL,
      state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'completed', 'aborted')),
      created_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD COLUMN IF NOT EXISTS designer_of_id text`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD COLUMN IF NOT EXISTS media_variant text`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD COLUMN IF NOT EXISTS review_status text`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD COLUMN IF NOT EXISTS visibility text`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD COLUMN IF NOT EXISTS publication_status text`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions DROP CONSTRAINT IF EXISTS upload_sessions_type_check`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD CONSTRAINT upload_sessions_type_check CHECK (type IN ('audio', 'video', 'original', 'subtitle'))`);
  await sql.unsafe(`CREATE UNIQUE INDEX IF NOT EXISTS upload_sessions_active_identity_idx ON ${ident}.upload_sessions (project, file_id, type, checksum_sha256) WHERE state = 'active'`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.subtitle_remux_jobs (
      id text PRIMARY KEY,
      project text NOT NULL,
      video_id text NOT NULL,
      source_id text NOT NULL,
      subtitle_id text NOT NULL,
      input_checksum_sha256 text NOT NULL,
      subtitle_checksum_sha256 text NOT NULL,
      state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'completed', 'failed', 'stale')),
      attempts integer NOT NULL DEFAULT 0,
      lease_token text,
      lease_until timestamptz,
      output_checksum_sha256 text,
      output_file_size bigint,
      last_error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project, video_id, input_checksum_sha256, subtitle_checksum_sha256)
    )
  `);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS subtitle_remux_jobs_claim_idx ON ${ident}.subtitle_remux_jobs (project, state, created_at)`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.source_processing (
      id text PRIMARY KEY,
      project text NOT NULL,
      source_id text NOT NULL,
      original_checksum_sha256 text NOT NULL,
      processing_profile text NOT NULL,
      state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'waiting', 'completed', 'failed', 'stale')),
      attempts integer NOT NULL DEFAULT 0,
      lease_token text,
      lease_until timestamptz,
      trim_plan jsonb,
      review_transcript text,
      generated_title text,
      srt_text text,
      waiting_reason text,
      last_error text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (project, source_id, original_checksum_sha256, processing_profile)
    )
  `);
  await sql.unsafe(`ALTER TABLE ${ident}.source_processing ADD COLUMN IF NOT EXISTS waiting_reason text`);
  await sql.unsafe(`ALTER TABLE ${ident}.source_processing DROP CONSTRAINT IF EXISTS source_processing_state_check`);
  await sql.unsafe(`ALTER TABLE ${ident}.source_processing ADD CONSTRAINT source_processing_state_check CHECK (state IN ('pending', 'claimed', 'waiting', 'completed', 'failed', 'stale'))`);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS source_processing_claim_idx ON ${ident}.source_processing (project, state, created_at)`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.project_overlay_logos (
      project text PRIMARY KEY,
      checksum_sha256 text NOT NULL,
      file_size bigint NOT NULL,
      updated_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.original_uploads (
      upload_id text PRIMARY KEY,
      project text NOT NULL,
      file_id text NOT NULL,
      mime_type text NOT NULL,
      original_filename text NOT NULL,
      checksum_sha256 text NOT NULL,
      file_size bigint NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.auth_tokens (
      kind text PRIMARY KEY CHECK (kind IN ('admin', 'media')),
      token_hash text NOT NULL,
      encrypted_token text,
      rotated_at timestamptz NOT NULL DEFAULT now(),
      version integer NOT NULL DEFAULT 1
    )
  `);
  await sql.unsafe(`ALTER TABLE ${ident}.auth_tokens ADD COLUMN IF NOT EXISTS encrypted_token text`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.admin_audit_log (
      id bigserial PRIMARY KEY,
      email text NOT NULL,
      action text NOT NULL,
      ip_address text,
      user_agent text,
      details jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now()
    )
  `);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS admin_audit_log_created_at_idx ON ${ident}.admin_audit_log (created_at DESC)`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.public_share_links (
      token_hash text PRIMARY KEY,
      project text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      revoked_at timestamptz
    )
  `);
  await sql.unsafe(`CREATE INDEX IF NOT EXISTS public_share_links_project_idx ON ${ident}.public_share_links (project, created_at DESC)`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.files LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.auth_tokens LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.admin_audit_log LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.public_share_links LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.upload_sessions LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.subtitle_remux_jobs LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.source_processing LIMIT 1`);
  await sql.unsafe(`SELECT 1 FROM ${ident}.project_overlay_logos LIMIT 1`);
}

/**
 * Link legacy derived files to their original upload when both use the same
 * pipeline file ID. New uploads set source_id directly; this only repairs
 * rows created before originals were tracked.
 */
export async function backfillLegacySourceLinks(): Promise<number> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ count: string }[]>(`
    WITH updated AS (
      UPDATE ${ident}.files AS derived
      SET source_id = original.id
      FROM ${ident}.files AS original
      WHERE derived.project = original.project
        AND derived.type IN ('audio', 'video')
        AND derived.source_id IS NULL
        AND original.type = 'original'
        AND derived.id = original.id
      RETURNING 1
    )
    SELECT COUNT(*)::text AS count FROM updated
  `);
  return Number(rows[0]?.count ?? 0);
}

/**
 * Repair companions uploaded before their dedicated `no-overlay` tag was
 * persisted. The exact source-ID relationship keeps this limited to genuine
 * linked pipeline companions with empty tags; it never changes content or
 * user-managed tags such as `trash`.
 */
export async function backfillLegacyNoOverlayTags(): Promise<number> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ count: string }[]>(`
    WITH updated AS (
      UPDATE ${ident}.files AS companion
      SET tags = '["no-overlay"]'::jsonb
      WHERE companion.type = 'video'
        AND companion.id LIKE '%-no-overlay'
        AND companion.source_id = left(companion.id, length(companion.id) - length('-no-overlay'))
        AND (CASE WHEN jsonb_typeof(companion.tags) = 'string'
                  THEN (companion.tags #>> '{}')::jsonb
                  ELSE companion.tags END) = '[]'::jsonb
        AND EXISTS (
          SELECT 1 FROM ${ident}.files AS original
          WHERE original.project = companion.project
            AND original.type = 'original'
            AND original.id = companion.source_id
        )
      RETURNING 1
    )
    SELECT COUNT(*)::text AS count FROM updated
  `);
  return Number(rows[0]?.count ?? 0);
}

/** Repair a legacy derived row as soon as its original is uploaded. */
export async function linkLegacyDerivedFilesForOriginal(
  project: string,
  originalId: string,
): Promise<number> {
  const sql = getDb();
  const ident = schemaIdent();
  const rows = await sql.unsafe<{ count: string }[]>(`
    WITH updated AS (
      UPDATE ${ident}.files AS derived
      SET source_id = original.id
      FROM ${ident}.files AS original
      WHERE derived.project = $1
        AND derived.id = $2
        AND derived.type IN ('audio', 'video')
        AND derived.source_id IS NULL
        AND original.project = derived.project
        AND original.id = derived.id
        AND original.type = 'original'
      RETURNING 1
    )
    SELECT COUNT(*)::text AS count FROM updated
  `, [project, originalId]);
  return Number(rows[0]?.count ?? 0);
}
