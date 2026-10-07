/**
 * Make a fresh test database for the isolated Compose stack.
 *
 * The fresh-database mode (docker-compose.isolated.fresh.yml) runs this script
 * in place of the database dump restore. It makes the schema with the app's
 * own startup bootstrap and adds the auth token rows that the flows use. It
 * uses no production data.
 */
import { closeDb, ensureDatabaseReady, getDb, schemaIdent } from "../../src/db.ts";

// SHA-256 of "test-token" (media) and "test-admin-token" (admin).
const TOKENS: Array<[string, string]> = [
  ["media", "4c5dc9b7708905f77f5e5d16316b5dfb425e68cb326dcd55a860e90a7707031e"],
  ["admin", "17d6bfe05d1b1fb7bc499f8e3f639c7b3eda4c40f321eef8887a0c04c89a99c5"],
];

await ensureDatabaseReady();
const sql = getDb();
const ident = schemaIdent();
for (const [kind, hash] of TOKENS) {
  await sql.unsafe(
    `INSERT INTO ${ident}.auth_tokens (kind, token_hash, encrypted_token) VALUES ($1, $2, NULL)
     ON CONFLICT (kind) DO UPDATE SET token_hash = EXCLUDED.token_hash`,
    [kind, hash],
  );
}
await closeDb();
console.log("fresh test database is ready");
