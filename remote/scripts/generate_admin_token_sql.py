#!/usr/bin/env python3
"""Generate a strong admin token plus SQL to seed Media Manager auth_tokens."""

import hashlib
import secrets


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


admin_token = "mm_admin_" + secrets.token_urlsafe(48)
token_hash = hashlib.sha256(admin_token.encode("utf-8")).hexdigest()

print(f"-- Admin token: {admin_token}")
print(
    f"""
insert into media_manager.auth_tokens (kind, token_hash)
values ('admin', {sql_literal(token_hash)})
on conflict (kind) do update
set token_hash = excluded.token_hash,
    rotated_at = now(),
    version = media_manager.auth_tokens.version + 1;
""".strip()
)
