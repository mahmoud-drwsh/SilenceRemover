/**
 * Minimal fetch-based API smoke tests against a running Media Manager instance.
 *
 * Usage:
 *   BASE_URL=http://127.0.0.1:3000 MEDIA_TOKEN=... ADMIN_TOKEN=... \
 *     node --import tsx scripts/test-api.ts
 *
 * Requires valid tokens in Supabase auth_tokens and a reachable DB/S3 (same as Python app).
 */
const BASE_URL = (process.env.BASE_URL ?? "http://127.0.0.1:3000").replace(/\/$/, "");
const MEDIA_TOKEN = process.env.MEDIA_TOKEN ?? "";
const ADMIN_TOKEN = process.env.ADMIN_TOKEN ?? "";
const PROJECT = process.env.PROJECT ?? "test-project";

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg);
}

async function main(): Promise<void> {
  if (!MEDIA_TOKEN) {
    console.warn("MEDIA_TOKEN unset — skipping authenticated tests.");
    return;
  }

  const listUrl = `${BASE_URL}/projects/${encodeURIComponent(MEDIA_TOKEN)}/${encodeURIComponent(PROJECT)}/api/files`;
  const list = await fetch(listUrl);
  assert(list.ok, `list files: ${list.status} ${await list.text()}`);
  const files = (await list.json()) as unknown;
  assert(Array.isArray(files), "list response must be array");
  console.log("ok: GET /projects/.../api/files");

  const check = await fetch(
    `${listUrl}?type=audio&check_id=nonexistent-id-${Date.now()}`,
  );
  assert(check.ok, `check_id: ${check.status}`);
  const checkJson = (await check.json()) as { exists?: boolean }[];
  assert(
    Array.isArray(checkJson) && checkJson[0]?.exists === false,
    "check_id not_found shape",
  );
  console.log("ok: check_id preflight (not found)");

  if (ADMIN_TOKEN) {
    const adminUrl = `${BASE_URL}/admin/${encodeURIComponent(ADMIN_TOKEN)}/api/projects`;
    const admin = await fetch(adminUrl);
    assert(admin.ok, `admin projects: ${admin.status} ${await admin.text()}`);
    const body = (await admin.json()) as { projects?: unknown; media_token?: unknown };
    assert(Array.isArray(body.projects), "admin projects array");
    console.log("ok: GET /admin/.../api/projects");
  } else {
    console.warn("ADMIN_TOKEN unset — skipping admin tests.");
  }

  console.log("\nAll executed tests passed.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
