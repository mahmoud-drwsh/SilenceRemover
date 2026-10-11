-- Media Manager plain-Postgres schema bootstrap.
--
-- The service makes and updates this schema at startup
-- (ensureDatabaseReady in src/server/db.ts), so a deploy needs no manual
-- database step. This file is the explicit SQL version of the same schema on
-- an empty database, for a manual bootstrap or a review. If you change the
-- startup schema, change this file too.
--
-- The schema name is media_manager (the DB_SCHEMA default). Apply with:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/setup_postgres.sql

create schema if not exists media_manager;

create table if not exists media_manager.files (
    id text not null,
    project text not null,
    type text not null check (type in ('audio', 'video', 'original')),
    title text,
    tags jsonb not null default '[]'::jsonb,
    duration double precision not null default 0,
    file_size bigint not null default 0,
    mime_type text not null,
    source_id text,
    original_filename text,
    checksum_sha256 text,
    designer_of_id text,
    active_designer_revision_id text,
    media_variant text,
    review_status text,
    visibility text,
    publication_status text,
    created_at timestamptz not null default now(),
    primary key (id, project, type)
);

create index if not exists files_project_type_idx
    on media_manager.files (project, type);
create index if not exists files_tags_gin_idx
    on media_manager.files using gin (tags);
create index if not exists files_project_source_idx
    on media_manager.files (project, source_id);
create index if not exists files_project_designer_of_idx
    on media_manager.files (project, designer_of_id);
create index if not exists files_project_active_designer_idx
    on media_manager.files (project, active_designer_revision_id);
create index if not exists files_project_variant_idx
    on media_manager.files (project, media_variant);

create table if not exists media_manager.upload_sessions (
    id text primary key,
    project text not null,
    file_id text not null,
    type text not null check (type in ('audio', 'video', 'original')),
    mime_type text not null,
    file_size bigint not null,
    checksum_sha256 text not null,
    title text not null default '',
    tags jsonb not null default '[]'::jsonb,
    source_id text,
    original_filename text,
    upload_id text,
    designer_of_id text,
    media_variant text,
    review_status text,
    visibility text,
    publication_status text,
    expires_at timestamptz not null,
    state text not null default 'active' check (state in ('active', 'completed', 'aborted')),
    created_at timestamptz not null default now()
);

create unique index if not exists upload_sessions_active_identity_idx
    on media_manager.upload_sessions (project, file_id, type, checksum_sha256)
    where state = 'active';

create table if not exists media_manager.source_processing (
    id text primary key,
    project text not null,
    source_id text not null,
    original_checksum_sha256 text not null,
    processing_profile text not null,
    state text not null default 'pending',
    attempts integer not null default 0,
    lease_token text,
    lease_until timestamptz,
    trim_plan jsonb,
    review_transcript text,
    generated_title text,
    waiting_reason text,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (project, source_id, original_checksum_sha256, processing_profile)
);

-- Startup drops and adds this constraint on each start. The name is the same
-- as the one that Postgres gives to an inline column check.
alter table media_manager.source_processing
    drop constraint if exists source_processing_state_check;
alter table media_manager.source_processing
    add constraint source_processing_state_check
    check (state in ('pending', 'claimed', 'waiting', 'completed', 'failed', 'stale'));

create index if not exists source_processing_claim_idx
    on media_manager.source_processing (project, state, created_at);

create table if not exists media_manager.original_uploads (
    upload_id text primary key,
    project text not null,
    file_id text not null,
    mime_type text not null,
    original_filename text not null,
    checksum_sha256 text not null,
    file_size bigint not null,
    created_at timestamptz not null default now()
);

create table if not exists media_manager.auth_tokens (
    kind text primary key check (kind in ('admin', 'media')),
    token_hash text not null,
    encrypted_token text,
    rotated_at timestamptz not null default now(),
    version integer not null default 1
);

create table if not exists media_manager.admin_audit_log (
    id bigserial primary key,
    email text not null,
    action text not null,
    ip_address text,
    user_agent text,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists admin_audit_log_created_at_idx
    on media_manager.admin_audit_log (created_at desc);
