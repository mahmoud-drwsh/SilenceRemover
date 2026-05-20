-- Media Manager plain-Postgres schema bootstrap.
-- Run once against the self-hosted Postgres database before deploying.

create schema if not exists media_manager;

create table if not exists media_manager.files (
    id text not null,
    project text not null,
    type text not null check (type in ('audio', 'video')),
    title text,
    tags jsonb not null default '[]'::jsonb,
    duration double precision not null default 0,
    file_size bigint not null default 0,
    mime_type text not null,
    created_at timestamptz not null default now(),
    primary key (id, project, type)
);

create index if not exists files_project_type_idx
    on media_manager.files (project, type);

create index if not exists files_tags_gin_idx
    on media_manager.files using gin (tags);

create table if not exists media_manager.auth_tokens (
    kind text primary key check (kind in ('admin', 'media')),
    token_hash text not null,
    encrypted_token text,
    rotated_at timestamptz not null default now(),
    version integer not null default 1
);

alter table media_manager.auth_tokens
    add column if not exists encrypted_token text;

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
