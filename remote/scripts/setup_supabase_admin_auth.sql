-- Media Manager token-auth prerequisites.
-- Run once in Supabase SQL editor or via psql before deploying the token-based app.

create extension if not exists supabase_vault cascade;

create table if not exists media_manager.admin_audit_log (
    id bigserial primary key,
    email text not null,
    action text not null,
    ip_address text,
    user_agent text,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

alter table media_manager.admin_audit_log enable row level security;
revoke all on media_manager.admin_audit_log from public, anon, authenticated;

alter table media_manager.auth_tokens
    add column if not exists vault_secret_id uuid;

-- Admin tokens are stored in media_manager.auth_tokens as SHA-256 hashes.
-- Generate the first token with:
--   python scripts/generate_admin_token_sql.py
