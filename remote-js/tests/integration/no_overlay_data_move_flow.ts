/**
 * Isolated Compose test for scripts/no_overlay_data_move.ts (#47).
 *
 * Run it with tests/integration/run_no_overlay_data_move_flow.sh. The runner
 * copies this file into the app container and runs it there, so the test uses
 * the same environment as the command.
 *
 * The test seeds all of its rows and objects. It also makes the legacy schema
 * (remux job table, logo table, SRT column, 'subtitle' type) when the startup
 * bootstrap does not make it, so it does not need a database dump.
 */
import { GetObjectCommand, HeadObjectCommand, ListObjectsV2Command, PutObjectCommand } from "@aws-sdk/client-s3";
import { randomUUID } from "node:crypto";
import { loadConfig } from "../../src/config.ts";
import { closeDb, getDb, schemaIdent } from "../../src/db.ts";
import { getS3Client } from "../../src/storage.ts";

const sql = getDb();
const ident = schemaIdent();
const bucket = loadConfig().s3Bucket;
const s3 = getS3Client();

function check(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Assertion failed: ${message}`);
}

function equal(actual: unknown, expected: unknown, message: string): void {
  const a = JSON.stringify(actual); const b = JSON.stringify(expected);
  if (a !== b) throw new Error(`Assertion failed: ${message}\n  actual:   ${a}\n  expected: ${b}`);
}

async function waitForApp(): Promise<void> {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    try { if ((await fetch("http://127.0.0.1:8080/healthz")).ok) return; } catch { /* not ready */ }
    await Bun.sleep(1000);
  }
  throw new Error("The app did not become healthy");
}

interface RunResult { code: number; stdout: string; stderr: string; summary: Record<string, any> | null }
function run(...args: string[]): RunResult {
  const result = Bun.spawnSync(["bun", "run", "scripts/no_overlay_data_move.ts", ...args], { cwd: "/app", stdout: "pipe", stderr: "pipe" });
  const stdout = result.stdout.toString(); const stderr = result.stderr.toString();
  const line = stdout.split("\n").reverse().find((item) => item.startsWith("SUMMARY "));
  const output = { code: result.exitCode ?? -1, stdout, stderr, summary: line ? JSON.parse(line.slice("SUMMARY ".length)) : null };
  for (const secret of ["minioadmin", "test-password", "X-Amz-Signature", "X-Amz-Credential", "0123456789abcdef0123456789abcdef"]) {
    check(!stdout.includes(secret) && !stderr.includes(secret), `output must not contain credentials or presigned URLs (${secret})`);
  }
  console.log(`-- ${args.join(" ")} -> exit ${output.code}`);
  // Show the script errors, so that a failed step is easy to diagnose.
  if (output.code !== 0 && stderr.trim() !== "") console.log(stderr.trim());
  return output;
}

async function put(key: string, body = "x".repeat(100)): Promise<void> {
  await s3.send(new PutObjectCommand({ Bucket: bucket, Key: key, Body: body }));
}

async function exists(key: string): Promise<boolean> {
  try { await s3.send(new HeadObjectCommand({ Bucket: bucket, Key: key })); return true; } catch { return false; }
}

async function listAll(): Promise<string[]> {
  const keys: string[] = []; let token: string | undefined;
  do {
    const page = await s3.send(new ListObjectsV2Command({ Bucket: bucket, ContinuationToken: token }));
    for (const item of page.Contents ?? []) keys.push(`${item.Key}:${item.Size}`);
    token = page.IsTruncated ? page.NextContinuationToken : undefined;
  } while (token);
  return keys.sort();
}

async function tableExists(name: string): Promise<boolean> {
  return Boolean((await sql.unsafe<{ oid: string | null }[]>(`SELECT to_regclass($1)::text oid`, [`${ident}.${name}`]))[0]?.oid);
}

async function snapshot(): Promise<string> {
  const files = await sql.unsafe(`SELECT * FROM ${ident}.files ORDER BY project,type,id`);
  const sessions = await sql.unsafe(`SELECT * FROM ${ident}.upload_sessions ORDER BY id`);
  const remux = await tableExists("subtitle_remux_jobs") ? await sql.unsafe(`SELECT * FROM ${ident}.subtitle_remux_jobs ORDER BY id`) : [];
  const logos = await tableExists("project_overlay_logos") ? await sql.unsafe(`SELECT * FROM ${ident}.project_overlay_logos ORDER BY project`) : [];
  const processing = await sql.unsafe(`SELECT * FROM ${ident}.source_processing ORDER BY id`);
  return JSON.stringify({ files, sessions, remux, logos, processing, objects: await listAll() });
}

type Seed = { id: string; type: string; title?: string; publication?: string | null; mime?: string; size?: number; source?: string | null; designerOf?: string | null; pointer?: string | null; variant?: string | null; tags?: string; visibility?: string | null; minute?: number };
async function seedFile(project: string, seed: Seed): Promise<void> {
  const mime = seed.mime ?? (seed.type === "audio" ? "audio/ogg" : seed.type === "subtitle" ? "application/x-subrip" : "video/mp4");
  const ext = mime === "audio/ogg" ? ".ogg" : mime === "application/x-subrip" ? ".srt" : ".mp4";
  await sql.unsafe(`
    INSERT INTO ${ident}.files (id,project,type,title,tags,file_size,mime_type,source_id,designer_of_id,active_designer_revision_id,media_variant,visibility,created_at,publication_status)
    VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11,$12, timestamptz '2026-01-01' + make_interval(mins => $13),$14)`,
  [seed.id, project, seed.type, seed.title ?? `Title ${seed.id}`, seed.tags ?? "[]", seed.size ?? 100, mime, seed.source ?? null, seed.designerOf ?? null, seed.pointer ?? null, seed.variant ?? null, seed.visibility ?? null, seed.minute ?? 0, seed.publication ?? null]);
  await put(`${seed.type}/${project}/${seed.id}${ext}`, "x".repeat(seed.size ?? 100));
}

async function fileRow(project: string, id: string, type = "video"): Promise<Record<string, any> | undefined> {
  return (await sql.unsafe(`SELECT * FROM ${ident}.files WHERE project=$1 AND id=$2 AND type=$3`, [project, id, type]))[0];
}

async function seedLegacySchema(): Promise<void> {
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.subtitle_remux_jobs (
      id text PRIMARY KEY, project text NOT NULL, video_id text NOT NULL, source_id text NOT NULL, subtitle_id text NOT NULL,
      input_checksum_sha256 text NOT NULL, subtitle_checksum_sha256 text NOT NULL, state text NOT NULL DEFAULT 'pending',
      attempts integer NOT NULL DEFAULT 0, lease_token text, lease_until timestamptz, output_checksum_sha256 text,
      output_file_size bigint, last_error text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())`);
  await sql.unsafe(`
    CREATE TABLE IF NOT EXISTS ${ident}.project_overlay_logos (
      project text PRIMARY KEY, checksum_sha256 text NOT NULL, file_size bigint NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())`);
  await sql.unsafe(`ALTER TABLE ${ident}.source_processing ADD COLUMN IF NOT EXISTS srt_text text`);
  await sql.unsafe(`ALTER TABLE ${ident}.files DROP CONSTRAINT IF EXISTS files_type_check`);
  await sql.unsafe(`ALTER TABLE ${ident}.files ADD CONSTRAINT files_type_check CHECK (type IN ('audio', 'video', 'original', 'subtitle'))`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions DROP CONSTRAINT IF EXISTS upload_sessions_type_check`);
  await sql.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD CONSTRAINT upload_sessions_type_check CHECK (type IN ('audio', 'video', 'original', 'subtitle'))`);
}

await waitForApp();
await seedLegacySchema();
const runId = randomUUID().slice(0, 8);
const P = `datamove-${runId}`;
const Q = `datamove-other-${runId}`;
const designerA = `s1-designer-${randomUUID()}`;
const designerB = `s1-designer-${randomUUID()}`;
const lonelyDesigner = `lonely-4-designer-${randomUUID()}`;
const designer7a = `s7-designer-${randomUUID()}`;
const designer7b = `s7-no-overlay-designer-${randomUUID()}`;

// ---- seed legacy rows and objects ----
for (const seed of [
  { id: "s1", type: "original" }, { id: "s1", type: "audio" },
  { id: "s1", type: "video", source: "s1", variant: "pipeline-final", pointer: designerA, size: 1000, title: "Approved s1" },
  { id: "s1-no-overlay", type: "video", source: "s1", variant: "no-overlay", size: 900, title: "Approved s1 (No Overlay)" },
  { id: designerA, type: "video", source: "s1", designerOf: "s1", variant: "designer", minute: 1 },
  { id: designerB, type: "video", source: "s1", designerOf: "s1", variant: "designer", minute: 2 },
  { id: "s1-subtitles", type: "subtitle", size: 50 },
  // Legacy rows: no explicit variant, tags encoded as a JSON string, a `-designer` row.
  { id: "s2", type: "original" },
  { id: "final-2", type: "video", source: "s2", tags: JSON.stringify(JSON.stringify(["pending"])), size: 2000 },
  { id: "final-2-no-overlay", type: "video", source: "s2", tags: JSON.stringify(["no-overlay"]) },
  { id: "final-2-designer", type: "video", tags: JSON.stringify(["designer"]), minute: 3 },
  // An old overlaid video with no original and no no-overlay video.
  { id: "old-3", type: "video", size: 3000 },
  // An overlaid video with a designer revision and no no-overlay video: it must stay.
  { id: "s4", type: "original" },
  { id: "lonely-4", type: "video", source: "s4", variant: "pipeline-final" },
  { id: lonelyDesigner, type: "video", source: "s4", designerOf: "lonely-4", variant: "designer" },
  // An active overlaid video whose no-overlay video is in trash: the overlaid
  // state is the card state, so the no-overlay video becomes active.
  { id: "s5", type: "original" },
  { id: "s5", type: "video", source: "s5", variant: "pipeline-final" },
  { id: "s5-no-overlay", type: "video", source: "s5", variant: "no-overlay", visibility: "trash", tags: JSON.stringify(["trash"]) },
  // An overlaid video in trash and pending: the no-overlay video gets the same state.
  { id: "s6", type: "original" },
  { id: "s6", type: "video", source: "s6", variant: "pipeline-final", visibility: "trash", publication: "pending", tags: JSON.stringify(["trash", "pending"]) },
  { id: "s6-no-overlay", type: "video", source: "s6", variant: "no-overlay", visibility: "active", publication: "published" },
  // The no-overlay video already has an active designer revision: it stays.
  { id: "s7", type: "original" },
  { id: "s7", type: "video", source: "s7", variant: "pipeline-final", pointer: designer7a },
  { id: "s7-no-overlay", type: "video", source: "s7", variant: "no-overlay", pointer: designer7b },
  { id: designer7a, type: "video", source: "s7", designerOf: "s7", variant: "designer", minute: 5 },
  { id: designer7b, type: "video", source: "s7", designerOf: "s7-no-overlay", variant: "designer", minute: 4 },
] as Seed[]) await seedFile(P, seed);
for (const seed of [
  { id: "q1", type: "original" },
  { id: "q1", type: "video", source: "q1", variant: "pipeline-final" },
  { id: "q1-no-overlay", type: "video", source: "q1", variant: "no-overlay" },
  { id: "q1-subtitles", type: "subtitle" },
] as Seed[]) await seedFile(Q, seed);
await put(`subtitle/${P}/ghost-subtitles.srt`);
await sql.unsafe(`INSERT INTO ${ident}.project_overlay_logos (project,checksum_sha256,file_size) VALUES ($1,$2,100)`, [P, "a".repeat(64)]);
await put(`project-overlay-logo/${encodeURIComponent(P)}.png`);
await sql.unsafe(`INSERT INTO ${ident}.subtitle_remux_jobs (id,project,video_id,source_id,subtitle_id,input_checksum_sha256,subtitle_checksum_sha256) VALUES ($1,$2,'s1','s1','s1-subtitles',$3,$3)`, [`remux-${runId}`, P, "b".repeat(64)]);
await put(`remux/${P}/remux-${runId}.mp4`);
const sessionSql = `INSERT INTO ${ident}.upload_sessions (id,project,file_id,type,mime_type,file_size,checksum_sha256,expires_at,state) VALUES ($1,$2,$3,$4,$5,100,$6,now() - interval '1 day','completed')`;
await sql.unsafe(sessionSql, [`sub-session-${runId}`, P, "s1-subtitles", "subtitle", "application/x-subrip", "c".repeat(64)]);
await sql.unsafe(sessionSql, [`video-session-${runId}`, P, "s1-no-overlay", "video", "video/mp4", "d".repeat(64)]);
for (const kind of ["subtitle", "overlaid_video", "review_audio", "no_overlay_video"]) await put(`source-processing/${P}/job-1/lease-1/${kind}`);

// ---- dry-run changes nothing ----
const beforeDry = await snapshot();
const dry = run("dry-run", `--project=${P}`);
equal(dry.code, 0, "dry-run exit code");
equal(await snapshot(), beforeDry, "dry-run makes no database or storage change");
const g = dry.summary!.groups;
const counts = Object.fromEntries(Object.entries(g).map(([name, value]: [string, any]) => [name, value.count]));
equal(counts, {
  designer_relinks: 4, active_pointer_moves: 2, pointer_conflicts: 1, title_copies: 1, state_copies: 3, overlaid_videos: 6,
  overlaid_videos_without_no_overlay: 1, overlaid_videos_with_trashed_no_overlay: 1, blocked_overlaid_videos: 1,
  unresolved_designers: 0, subtitle_files: 1, subtitle_orphan_objects: 1, project_logos: 1, logo_orphan_objects: 0,
  remux_jobs: 1, subtitle_upload_sessions: 1, remux_temp_objects: 1, worker_temp_objects: 2,
}, "dry-run group counts");
equal(g.overlaid_videos.bytes, 1000 + 2000 + 3000 + 100 * 3, "dry-run overlaid bytes");
for (const id of ["old-3", "final-2-designer", "lonely-4", `remux-${runId}`, `sub-session-${runId}`, `source-processing/${P}/job-1/lease-1/overlaid_video`]) {
  check(dry.stdout.includes(id), `dry-run lists ${id}`);
}
check(/s5-no-overlay .*visibility=trash->active.*tags=\["trash"\]->\[\]/.test(dry.stdout), "dry-run shows the state before and after the copy");

// ---- apply needs --confirm ----
equal(run("apply", `--project=${P}`).code, 2, "apply without --confirm is refused");
equal(run("drop-schema").code, 2, "drop-schema without --confirm is refused");
equal(await snapshot(), beforeDry, "a refused command makes no change");

// ---- an apply that stops in the middle ----
const otherBefore = JSON.stringify(await sql.unsafe(`SELECT * FROM ${ident}.files WHERE project=$1 ORDER BY type,id`, [Q]));
const stopped = run("apply", "--confirm", `--project=${P}`, "--stop-after=2");
equal(stopped.code, 4, "apply stops after two delete steps");
for (const id of [designerA, designerB]) equal((await fileRow(P, id))?.designer_of_id, "s1-no-overlay", `${id} moved before any delete`);
equal((await fileRow(P, "s1-no-overlay"))?.active_designer_revision_id, designerA, "pointer moved before any delete");

// ---- apply finishes ----
const applied = run("apply", "--confirm", `--project=${P}`);
equal(applied.code, 3, "apply finishes and reports the blocked row");
equal((await fileRow(P, "s1-no-overlay"))?.active_designer_revision_id, designerA, "the same active designer video stays on the s1 card");
equal((await fileRow(P, "final-2-no-overlay"))?.active_designer_revision_id, "final-2-designer", "the legacy card keeps its designer video");
equal((await fileRow(P, "s7-no-overlay"))?.active_designer_revision_id, designer7b, "a pointer on the no-overlay row is not overwritten");
equal((await fileRow(P, designer7a))?.designer_of_id, "s7-no-overlay", "the s7 revision moves to the no-overlay video");
equal((await fileRow(P, "s1-no-overlay"))?.title, "Approved s1", "the approved title replaces a title that ends with (No Overlay)");
equal((await fileRow(P, "final-2-no-overlay"))?.title, "Title final-2-no-overlay", "a title that the card already has stays");
const s6 = await fileRow(P, "s6-no-overlay");
equal([s6?.visibility, s6?.publication_status, s6?.tags], ["trash", "pending", ["trash"]], "trash and pending state go to the no-overlay video");
const f2 = await fileRow(P, "final-2-no-overlay");
equal([f2?.publication_status, f2?.tags], ["pending", ["no-overlay"]], "the legacy pending state goes to the no-overlay video");
const s5 = await fileRow(P, "s5-no-overlay");
equal([s5?.visibility, s5?.tags], ["active", []], "an active overlaid card makes its trashed no-overlay video active");
const legacy = await fileRow(P, "final-2-designer");
equal([legacy?.designer_of_id, legacy?.media_variant, legacy?.source_id], ["final-2-no-overlay", "designer", "s2"], "the legacy -designer row has an explicit target");
for (const id of ["s1", "final-2", "old-3", "s5", "s6", "s7"]) {
  check(!(await fileRow(P, id)), `overlaid row ${id} is deleted`);
  check(!(await exists(`video/${P}/${id}.mp4`)), `overlaid object ${id} is deleted`);
}
check(await fileRow(P, "lonely-4"), "a blocked overlaid row stays");
check(await exists(`video/${P}/lonely-4.mp4`), "a blocked overlaid object stays");
const kept: Array<[string, string, string]> = [
  ["s1", "original", ".mp4"], ["s2", "original", ".mp4"], ["s4", "original", ".mp4"], ["s5", "original", ".mp4"], ["s1", "audio", ".ogg"],
  ["s1-no-overlay", "video", ".mp4"], ["final-2-no-overlay", "video", ".mp4"], ["s5-no-overlay", "video", ".mp4"],
  ["s6-no-overlay", "video", ".mp4"], ["s7-no-overlay", "video", ".mp4"], [designer7a, "video", ".mp4"], [designer7b, "video", ".mp4"],
  [designerA, "video", ".mp4"], [designerB, "video", ".mp4"], ["final-2-designer", "video", ".mp4"], [lonelyDesigner, "video", ".mp4"],
];
for (const [id, type, ext] of kept) {
  check(await fileRow(P, id, type), `${type} ${id} row stays`);
  check(await exists(`${type}/${P}/${id}${ext}`), `${type} ${id} object stays`);
}
check(!(await fileRow(P, "s1-subtitles", "subtitle")), "SRT row is deleted");
for (const key of [`subtitle/${P}/s1-subtitles.srt`, `subtitle/${P}/ghost-subtitles.srt`, `project-overlay-logo/${encodeURIComponent(P)}.png`, `remux/${P}/remux-${runId}.mp4`,
  `source-processing/${P}/job-1/lease-1/subtitle`, `source-processing/${P}/job-1/lease-1/overlaid_video`]) check(!(await exists(key)), `${key} is deleted`);
for (const key of [`source-processing/${P}/job-1/lease-1/review_audio`, `source-processing/${P}/job-1/lease-1/no_overlay_video`]) check(await exists(key), `${key} stays`);
equal((await sql.unsafe(`SELECT count(*)::int n FROM ${ident}.project_overlay_logos WHERE project=$1`, [P]))[0]?.n, 0, "logo row is deleted");
equal((await sql.unsafe(`SELECT count(*)::int n FROM ${ident}.subtitle_remux_jobs WHERE project=$1`, [P]))[0]?.n, 0, "remux jobs are deleted");
equal((await sql.unsafe(`SELECT id FROM ${ident}.upload_sessions WHERE project=$1 ORDER BY id`, [P])).map((row: any) => row.id), [`video-session-${runId}`], "only the subtitle session is deleted");
equal(JSON.stringify(await sql.unsafe(`SELECT * FROM ${ident}.files WHERE project=$1 ORDER BY type,id`, [Q])), otherBefore, "another project does not change");

// ---- a second apply finds nothing to do ----
const second = run("apply", "--confirm", `--project=${P}`);
equal(second.code, 3, "second apply still reports the blocked row");
equal(second.summary!.done, {}, "second apply does nothing");
const dry2 = run("dry-run", `--project=${P}`);
equal(dry2.summary!.work_left, 0, "dry-run after apply finds no work");
equal(dry2.summary!.groups.blocked_overlaid_videos.count, 1, "the blocked row is still reported");

// ---- drop-schema refuses while subtitle rows remain ----
const beforeDrop = await snapshot();
equal(run("drop-schema", "--confirm").code, 2, "drop-schema refuses while subtitle rows remain");
equal(await snapshot(), beforeDrop, "a refused drop-schema makes no change");

// ---- apply on all projects, then drop-schema twice ----
const all = run("apply", "--confirm");
check(all.code === 0 || all.code === 3, `apply on all projects finishes (exit ${all.code}): ${all.stderr}`);
console.log(`   all projects: ${JSON.stringify(all.summary?.done)} refused=${all.summary?.refused?.length}`);
check(!(await fileRow(Q, "q1")), "the other project's overlaid row is deleted");
check(await fileRow(Q, "q1-no-overlay"), "the other project's no-overlay row stays");
for (const mode of ["first", "second"]) {
  const dropped = run("drop-schema", "--confirm");
  equal(dropped.code, 0, `drop-schema (${mode}) exit code: ${dropped.stderr}`);
  equal(dropped.summary!.schema, {
    subtitle_remux_jobs_table: false, project_overlay_logos_table: false, srt_text_column: false, jobs_with_srt_text: 0,
    files_type_check_has_subtitle: false, upload_sessions_type_check_has_subtitle: false,
  }, `schema after drop-schema (${mode})`);
}
let rejected = false;
try {
  await sql.unsafe(`INSERT INTO ${ident}.files (id,project,type,mime_type) VALUES ('x-subtitles',$1,'subtitle','application/x-subrip')`, [P]);
} catch { rejected = true; }
check(rejected, "the files type constraint rejects 'subtitle'");
const dry3 = run("dry-run", `--project=${P}`);
equal(dry3.code, 0, "dry-run works after drop-schema");
check(await s3.send(new GetObjectCommand({ Bucket: bucket, Key: `video/${P}/s1-no-overlay.mp4` })), "no-overlay object is still readable");

await closeDb();
console.log("no_overlay_data_move_flow: OK");
