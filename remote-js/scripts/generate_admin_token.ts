/**
 * Print a fresh admin token plus the SQL needed to seed it into
 * `media_manager.auth_tokens`.
 *
 * Usage:
 *   bun run scripts/generate_admin_token.ts
 *   bun run generate-admin-token
 *
 * Output:
 *   -- Admin token: <opaque token>
 *   insert into media_manager.auth_tokens (kind, token_hash) ...
 */

import { createHash, randomBytes } from "node:crypto";

function sqlLiteral(value: string): string {
  return "'" + value.replaceAll("'", "''") + "'";
}

const adminToken = "mm_admin_" + randomBytes(48).toString("base64url");
const tokenHash = createHash("sha256").update(adminToken, "utf-8").digest("hex");

console.log(`-- Admin token: ${adminToken}`);
console.log(
  `\ninsert into media_manager.auth_tokens (kind, token_hash)\nvalues ('admin', ${sqlLiteral(tokenHash)})\non conflict (kind) do update\nset token_hash = excluded.token_hash,\n    rotated_at = now(),\n    version = media_manager.auth_tokens.version + 1;`,
);
