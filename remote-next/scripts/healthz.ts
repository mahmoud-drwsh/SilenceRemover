/**
 * CLI health check: Postgres + S3 (same probes as /api/healthz).
 * Usage: SUPABASE_DATABASE_URL=... S3_*=... node --import tsx scripts/healthz.ts
 */
import { initDb } from "../src/lib/db";

async function main(): Promise<void> {
  await initDb();
  console.log("ok");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
