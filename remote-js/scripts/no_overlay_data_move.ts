/**
 * Operator command for the no-overlay data move (#44, #47, #49).
 *
 * Modes:
 *   dry-run      Reads the database and the object store. Changes nothing.
 *   apply        Moves designer links and active pointers to the no-overlay
 *                video, then deletes the overlaid videos, SRTs, logos, remux
 *                jobs, subtitle upload sessions and the temp objects of the
 *                removed kinds. Needs --confirm. Safe to run again.
 *   drop-schema  Drops the removed tables and column and removes 'subtitle'
 *                from the type constraints. Needs --confirm. Refuses while
 *                subtitle rows or subtitle upload sessions remain.
 *
 * Options:
 *   --project=<name>   Limit dry-run and apply to one project.
 *   --max-ids=<n>      Print at most n IDs for each group (default: all).
 *   --stop-after=<n>   Test only: stop apply after n delete steps (exit 4).
 *
 * Exit codes: 0 done, 1 error, 2 refused, 3 apply left blocked rows, 4 stopped.
 *
 * Run it in the Media Manager service container. It uses the service
 * environment. It prints no credentials and no presigned URLs.
 * It does not call the startup bootstrap, because the bootstrap can re-create
 * the removed schema.
 */
import { AbortMultipartUploadCommand, DeleteObjectCommand, ListObjectsV2Command } from "@aws-sdk/client-s3";
import type { TransactionSql } from "postgres";
import { loadConfig } from "../src/config.ts";
import { closeDb, getDb, schemaIdent } from "../src/db.ts";
import { MIME_TO_EXT, getExtensionForMime } from "../src/mime.ts";
import {
  isRemovedWorkerTempKey, isRemuxTempKey, isSubtitleKey,
  parseTags, planNoOverlayDataMove, remuxTempPrefix, subtitlePrefix, toBytes, deleteRowWithObjects, workerTempPrefix,
  type DataMovePlan, type OverlaidItem, type StateCopy, type VideoRow,
} from "../src/noOverlayDataMove.ts";
import { getS3Client, storageObjectKey } from "../src/storage.ts";
import { publicationStatusSql, videoVariantSql, visibilitySql } from "../src/videoSql.ts";

type Mode = "dry-run" | "apply" | "drop-schema";

class Refusal extends Error {}
class StopRequested extends Error {}

const argv = process.argv.slice(2);
const mode = argv.find((arg) => !arg.startsWith("--")) as Mode | undefined;
const confirm = argv.includes("--confirm");
const option = (name: string): string | undefined => argv.find((arg) => arg.startsWith(`--${name}=`))?.slice(name.length + 3);
const project = option("project") ?? null;
const maxIds = option("max-ids") === undefined ? Number.POSITIVE_INFINITY : Number(option("max-ids"));
const stopAfter = option("stop-after") === undefined ? null : Number(option("stop-after"));

const sql = getDb();
const ident = schemaIdent();
const bucket = loadConfig().s3Bucket;
const s3 = getS3Client();

/*
 * Object keys of the removed features. The app does not make these objects
 * any more, so these keys are only in this script. The command needs them only
 * to delete the legacy objects.
 */
const LOGO_PREFIX = "project-overlay-logo/";
function logoObjectKey(projectName: string): string {
  return `${LOGO_PREFIX}${encodeURIComponent(projectName)}.png`;
}
function isLogoKey(objectKey: string, projectName: string | null): boolean {
  if (!/^project-overlay-logo\/[^/]+\.png$/.test(objectKey)) return false;
  return projectName === null || objectKey === logoObjectKey(projectName);
}
function subtitleFileKey(projectName: string, id: string, ext: string): string {
  return `subtitle/${projectName}/${id}${ext}`;
}

/** A designer revision that still points at the overlaid row `f`. */
const POINTS_AT_F = `EXISTS (SELECT 1 FROM ${ident}.files d WHERE d.project=f.project AND d.type='video' AND (d.designer_of_id=f.id OR (d.designer_of_id IS NULL AND d.id=f.id || '-designer')))`;

interface Item { project: string; id: string; bytes: number; detail?: string }
interface Group { count: number; bytes: number; items: Item[] }
interface SchemaState {
  subtitle_remux_jobs_table: boolean;
  project_overlay_logos_table: boolean;
  srt_text_column: boolean;
  jobs_with_srt_text: number;
  files_type_check_has_subtitle: boolean;
  upload_sessions_type_check_has_subtitle: boolean;
}
interface ObjectEntry { key: string; size: number }
interface SubtitleRow { project: string; id: string; file_size: string | number; mime_type: string }
interface SessionRow { id: string; project: string; file_id: string; file_size: string | number; state: string; upload_id: string | null; mime_type: string; expires_at: Date }
interface Inventory {
  plan: DataMovePlan;
  subtitles: SubtitleRow[];
  subtitleOrphans: ObjectEntry[];
  logos: Array<{ project: string; file_size: string | number }>;
  logoOrphans: ObjectEntry[];
  remuxJobs: Array<{ id: string; project: string; state: string }>;
  sessions: SessionRow[];
  remuxTemps: ObjectEntry[];
  workerTemps: ObjectEntry[];
  schema: SchemaState;
}

function group(items: Item[]): Group {
  return { count: items.length, bytes: items.reduce((sum, item) => sum + item.bytes, 0), items };
}

function objectItem(entry: ObjectEntry): Item {
  return { project: entry.key.split("/")[1] ?? "", id: entry.key, bytes: entry.size };
}

async function tableExists(name: string): Promise<boolean> {
  const rows = await sql.unsafe<{ oid: string | null }[]>(`SELECT to_regclass($1)::text AS oid`, [`${ident}.${name}`]);
  return Boolean(rows[0]?.oid);
}

async function schemaState(): Promise<SchemaState> {
  const schemaName = loadConfig().dbSchema;
  const column = await sql.unsafe<{ n: string }[]>(
    `SELECT count(*)::text n FROM information_schema.columns WHERE table_schema=$1 AND table_name='source_processing' AND column_name='srt_text'`, [schemaName]);
  const srtColumn = Number(column[0]?.n ?? 0) > 0;
  const withSrt = srtColumn
    ? Number((await sql.unsafe<{ n: string }[]>(`SELECT count(*)::text n FROM ${ident}.source_processing WHERE srt_text IS NOT NULL`))[0]?.n ?? 0)
    : 0;
  const checks = await sql.unsafe<{ conname: string; def: string }[]>(`
    SELECT c.conname, pg_get_constraintdef(c.oid) AS def
    FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
    WHERE n.nspname=$1 AND c.conname IN ('files_type_check','upload_sessions_type_check')`, [schemaName]);
  const hasSubtitle = (name: string) => checks.some((row) => row.conname === name && row.def.includes("'subtitle'"));
  return {
    subtitle_remux_jobs_table: await tableExists("subtitle_remux_jobs"),
    project_overlay_logos_table: await tableExists("project_overlay_logos"),
    srt_text_column: srtColumn,
    jobs_with_srt_text: withSrt,
    files_type_check_has_subtitle: hasSubtitle("files_type_check"),
    upload_sessions_type_check_has_subtitle: hasSubtitle("upload_sessions_type_check"),
  };
}

async function listObjects(prefix: string): Promise<ObjectEntry[]> {
  const out: ObjectEntry[] = [];
  let token: string | undefined;
  do {
    const page = await s3.send(new ListObjectsV2Command({ Bucket: bucket, Prefix: prefix, ContinuationToken: token }));
    for (const object of page.Contents ?? []) {
      if (object.Key && !object.Key.endsWith("/")) out.push({ key: object.Key, size: Number(object.Size ?? 0) });
    }
    token = page.IsTruncated ? page.NextContinuationToken : undefined;
  } while (token);
  return out;
}

async function loadVideos(): Promise<VideoRow[]> {
  return sql.unsafe<VideoRow[]>(`
    SELECT project,id,source_id,designer_of_id,active_designer_revision_id,media_variant,tags,title,review_status,visibility,publication_status,file_size,mime_type,created_at
    FROM ${ident}.files WHERE type='video' AND ($1::text IS NULL OR project=$1) ORDER BY project,id`, [project]);
}

async function inventory(): Promise<Inventory> {
  const schema = await schemaState();
  const plan = planNoOverlayDataMove(await loadVideos());
  const subtitles = await sql.unsafe<SubtitleRow[]>(
    `SELECT project,id,file_size,mime_type FROM ${ident}.files WHERE type='subtitle' AND ($1::text IS NULL OR project=$1) ORDER BY project,id`, [project]);
  const subtitleKeys = new Set(subtitles.flatMap((row) => subtitleObjectKeys(row)));
  const subtitleOrphans = (await listObjects(subtitlePrefix(project))).filter((entry) => isSubtitleKey(entry.key) && !subtitleKeys.has(entry.key));
  const logos = schema.project_overlay_logos_table
    ? await sql.unsafe<{ project: string; file_size: string | number }[]>(
      `SELECT project,file_size FROM ${ident}.project_overlay_logos WHERE ($1::text IS NULL OR project=$1) ORDER BY project`, [project])
    : [];
  const logoKeys = new Set(logos.map((row) => logoObjectKey(row.project)));
  const logoOrphans = (await listObjects(LOGO_PREFIX)).filter((entry) => isLogoKey(entry.key, project) && !logoKeys.has(entry.key));
  const remuxJobs = schema.subtitle_remux_jobs_table
    ? await sql.unsafe<{ id: string; project: string; state: string }[]>(
      `SELECT id,project,state FROM ${ident}.subtitle_remux_jobs WHERE ($1::text IS NULL OR project=$1) ORDER BY project,created_at,id`, [project])
    : [];
  const sessions = await sql.unsafe<SessionRow[]>(
    `SELECT id,project,file_id,file_size,state,upload_id,mime_type,expires_at FROM ${ident}.upload_sessions WHERE type='subtitle' AND ($1::text IS NULL OR project=$1) ORDER BY project,created_at,id`, [project]);
  const remuxTemps = (await listObjects(remuxTempPrefix(project))).filter((entry) => isRemuxTempKey(entry.key));
  const workerTemps = (await listObjects(workerTempPrefix(project))).filter((entry) => isRemovedWorkerTempKey(entry.key));
  return { plan, subtitles, subtitleOrphans, logos, logoOrphans, remuxJobs, sessions, remuxTemps, workerTemps, schema };
}

function groups(inv: Inventory): Record<string, Group> {
  const { plan } = inv;
  const overlaid = (items: OverlaidItem[]) => items.map((item) => ({
    project: item.project, id: item.id, bytes: item.file_size,
    detail: item.companion_id ? `no-overlay=${item.companion_id}${item.companion_trashed ? " (no-overlay video is in trash)" : ""}` : "no no-overlay video",
  }));
  return {
    designer_relinks: group(plan.designer_relinks.map((row) => ({ project: row.project, id: row.id, bytes: 0, detail: `${row.from_target} -> ${row.to_target}${row.legacy_suffix ? " (legacy -designer row)" : ""}` }))),
    active_pointer_moves: group(plan.pointer_moves.map((row) => ({ project: row.project, id: row.no_overlay_id, bytes: 0, detail: `revision=${row.revision_id} from=${row.overlaid_id}${row.implicit ? " (implicit newest revision)" : ""}` }))),
    pointer_conflicts: group(plan.pointer_conflicts.map((row) => ({ project: row.project, id: row.no_overlay_id, bytes: 0, detail: `overlaid=${row.overlaid_revision_id} no-overlay=${row.no_overlay_revision_id} kept=${row.kept_revision_id}` }))),
    title_copies: group(plan.title_copies.map((row) => ({ project: row.project, id: row.no_overlay_id, bytes: 0, detail: `from=${row.overlaid_id} title=${JSON.stringify(row.title)} previous=${JSON.stringify(row.previous)}` }))),
    state_copies: group(plan.state_copies.map((row) => ({ project: row.project, id: row.no_overlay_id, bytes: 0, detail: stateDetail(row) }))),
    overlaid_videos: group(overlaid(plan.overlaid_deletes)),
    overlaid_videos_without_no_overlay: group(overlaid(plan.overlaid_deletes.filter((item) => !item.companion_id))),
    overlaid_videos_with_trashed_no_overlay: group(overlaid(plan.overlaid_deletes.filter((item) => item.companion_trashed))),
    blocked_overlaid_videos: group(plan.blocked_overlaid.map((row) => ({ project: row.project, id: row.id, bytes: 0, detail: `${row.reason}; designer=${row.designer_ids.join(",")}` }))),
    unresolved_designers: group(plan.unresolved_designers.map((row) => ({ project: row.project, id: row.id, bytes: 0, detail: row.reason }))),
    subtitle_files: group(inv.subtitles.map((row) => ({ project: row.project, id: row.id, bytes: toBytes(row.file_size) }))),
    subtitle_orphan_objects: group(inv.subtitleOrphans.map(objectItem)),
    project_logos: group(inv.logos.map((row) => ({ project: row.project, id: logoObjectKey(row.project), bytes: toBytes(row.file_size) }))),
    logo_orphan_objects: group(inv.logoOrphans.map(objectItem)),
    remux_jobs: group(inv.remuxJobs.map((row) => ({ project: row.project, id: row.id, bytes: 0, detail: row.state }))),
    subtitle_upload_sessions: group(inv.sessions.map((row) => ({ project: row.project, id: row.id, bytes: toBytes(row.file_size), detail: `file=${row.file_id} state=${row.state}` }))),
    remux_temp_objects: group(inv.remuxTemps.map(objectItem)),
    worker_temp_objects: group(inv.workerTemps.map(objectItem)),
  };
}

/** Groups that apply must bring to zero. Info groups are not in this list. */
const WORK_GROUPS = [
  "designer_relinks", "active_pointer_moves", "title_copies", "state_copies", "overlaid_videos", "subtitle_files", "subtitle_orphan_objects",
  "project_logos", "logo_orphan_objects", "remux_jobs", "subtitle_upload_sessions", "remux_temp_objects", "worker_temp_objects",
];

/** Before and after state of one state copy, for example `visibility=trash->active`. */
function stateDetail(row: StateCopy): string {
  const parts = [`from=${row.overlaid_id}`];
  for (const name of ["visibility", "publication_status", "review_status"] as const) {
    const before = row.before[name]; const after = row.after[name];
    parts.push(before === after ? `${name}=${before ?? "none"}` : `${name}=${before ?? "none"}->${after ?? "none"}`);
  }
  const previous = parseTags(row.previous_tags);
  if (JSON.stringify(previous) !== JSON.stringify(row.tags)) parts.push(`tags=${JSON.stringify(previous)}->${JSON.stringify(row.tags)}`);
  return parts.join(" ");
}

function printReport(title: string, all: Record<string, Group>, schema: SchemaState): void {
  console.log(`# ${title}`);
  for (const [name, value] of Object.entries(all)) {
    console.log(`== ${name}: count=${value.count} bytes=${value.bytes} (${formatBytes(value.bytes)})`);
    for (const item of value.items.slice(0, maxIds)) {
      console.log(`   ${item.project} ${item.id} bytes=${item.bytes}${item.detail ? ` ${item.detail}` : ""}`);
    }
    if (value.items.length > maxIds) console.log(`   ... ${value.items.length - maxIds} more`);
  }
  console.log(`== schema: ${JSON.stringify(schema)}`);
}

function summary(all: Record<string, Group>): Record<string, { count: number; bytes: number }> {
  return Object.fromEntries(Object.entries(all).map(([name, value]) => [name, { count: value.count, bytes: value.bytes }]));
}

function formatBytes(bytes: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = bytes; let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit === 0 ? 0 : 2)} ${units[unit]}`;
}

function subtitleObjectKeys(row: SubtitleRow): string[] {
  const exts = new Set([".srt", getExtensionForMime(row.mime_type)]);
  exts.delete(".bin");
  return [...exts].map((ext) => subtitleFileKey(row.project, row.id, ext));
}

function overlaidObjectKeys(item: OverlaidItem): string[] {
  const ext = getExtensionForMime(item.mime_type);
  // A wrong legacy MIME gives no known extension. Then try every known one,
  // as the file delete route does. Each key is only this row's own ID.
  const exts = ext === ".bin" ? [...new Set(Object.values(MIME_TO_EXT))] : [ext];
  return exts.map((value) => storageObjectKey("video", item.project, item.id, value));
}

// ---- apply ----------------------------------------------------------------

const done: Record<string, number> = {};
let steps = 0;
function count(name: string): void {
  done[name] = (done[name] ?? 0) + 1;
  steps += 1;
  if (stopAfter !== null && steps >= stopAfter) throw new StopRequested(`Stopped after ${steps} delete steps (--stop-after)`);
}

async function deleteObject(objectKey: string): Promise<void> {
  // The keys come from database rows or from dedicated prefixes. Never delete
  // originals, review audio or kept videos by prefix.
  if (/^(original|audio)\//.test(objectKey)) throw new Error(`Refusing to delete a protected object: ${objectKey}`);
  try {
    await s3.send(new DeleteObjectCommand({ Bucket: bucket, Key: objectKey }));
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    if (name !== "NoSuchKey" && name !== "NotFound") throw error;
  }
}

async function relinkAndMovePointers(plan: DataMovePlan): Promise<void> {
  if (moveWork(plan) === 0) return;
  await sql.begin(async (tx) => {
    for (const row of plan.designer_relinks) {
      const updated = await tx.unsafe(`
        UPDATE ${ident}.files d
        SET designer_of_id=$3, media_variant='designer',
            source_id=COALESCE(d.source_id, (SELECT n.source_id FROM ${ident}.files n WHERE n.project=d.project AND n.id=$3 AND n.type='video'))
        WHERE d.project=$1 AND d.id=$2 AND d.type='video'
          AND (d.designer_of_id=$4 OR (d.designer_of_id IS NULL AND d.id=$4 || '-designer'))
          AND EXISTS (SELECT 1 FROM ${ident}.files n WHERE n.project=d.project AND n.id=$3 AND n.type='video' AND ${videoVariantSql("n")}='no-overlay')
        RETURNING d.id`, [row.project, row.id, row.to_target, row.from_target]);
      if (updated.length !== 1) throw new Error(`Designer revision ${row.project}/${row.id} changed during apply. Run apply again.`);
    }
    for (const move of plan.pointer_moves) {
      const updated = await tx.unsafe(`
        UPDATE ${ident}.files n SET active_designer_revision_id=$3
        WHERE n.project=$1 AND n.id=$2 AND n.type='video' AND ${videoVariantSql("n")}='no-overlay'
          AND n.active_designer_revision_id IS NOT DISTINCT FROM $4
        RETURNING n.id`, [move.project, move.no_overlay_id, move.revision_id, move.previous]);
      if (updated.length !== 1) throw new Error(`Active pointer of ${move.project}/${move.no_overlay_id} changed during apply. Run apply again.`);
    }
    for (const copy of plan.title_copies) {
      const updated = await tx.unsafe(`
        UPDATE ${ident}.files n SET title=$3
        WHERE n.project=$1 AND n.id=$2 AND n.type='video' AND ${videoVariantSql("n")}='no-overlay'
          AND n.title IS NOT DISTINCT FROM $4
        RETURNING n.id`, [copy.project, copy.no_overlay_id, copy.title, copy.previous]);
      if (updated.length !== 1) throw new Error(`Title of ${copy.project}/${copy.no_overlay_id} changed during apply. Run apply again.`);
    }
    for (const copy of plan.state_copies) {
      // Guard: the no-overlay row has the same columns and tags as in the plan,
      // and the overlaid row still has the state that the copy writes. Tag
      // parameters use $n::text::jsonb, so that the server parses the JSON
      // text and the client does not encode it a second time. The tag guard
      // compares the stored value exactly, also a legacy JSON-string value.
      const updated = await tx.unsafe(`
        UPDATE ${ident}.files n
        SET visibility=$3, publication_status=$4, review_status=$5, tags=$6::text::jsonb
        WHERE n.project=$1 AND n.id=$2 AND n.type='video' AND ${videoVariantSql("n")}='no-overlay'
          AND n.visibility IS NOT DISTINCT FROM $7 AND n.publication_status IS NOT DISTINCT FROM $8
          AND n.review_status IS NOT DISTINCT FROM $9
          AND n.tags = $10::text::jsonb
          AND EXISTS (SELECT 1 FROM ${ident}.files o
            WHERE o.project=n.project AND o.id=$11 AND o.type='video' AND ${videoVariantSql("o")}='pipeline-final'
              AND ${visibilitySql("o")}=$3 AND ${publicationStatusSql("o")}=$4
              AND ($12::text IS NULL OR o.review_status=$12))
        RETURNING n.id`, [
        copy.project, copy.no_overlay_id, copy.after.visibility, copy.after.publication_status, copy.after.review_status,
        JSON.stringify(copy.tags), copy.previous.visibility, copy.previous.publication_status, copy.previous.review_status,
        JSON.stringify(copy.previous_tags), copy.overlaid_id, copy.after.review_status === copy.before.review_status ? null : copy.after.review_status,
      ]);
      if (updated.length !== 1) throw new Error(`State of ${copy.project}/${copy.no_overlay_id} changed during apply. Run apply again.`);
    }
  });
  done.designer_relinks = plan.designer_relinks.length;
  done.active_pointer_moves = plan.pointer_moves.length;
  done.title_copies = plan.title_copies.length;
  done.state_copies = plan.state_copies.length;
}

/** Link, pointer, title and state work that must be done before any delete. */
function moveWork(plan: DataMovePlan): number {
  return plan.designer_relinks.length + plan.pointer_moves.length + plan.title_copies.length + plan.state_copies.length;
}

/**
 * Guards for the delete of the overlaid row `f`. It is a pipeline-final video
 * that is not a designer or no-overlay row, and no designer revision points
 * at it. When the plan found a companion ($3), that no-overlay row must still
 * exist. When the plan found none, the row must have no active pointer.
 */
const OVERLAID_DELETE_GUARDS = `
      f.type='video'
      AND f.designer_of_id IS NULL AND f.id NOT LIKE '%-designer' AND f.id NOT LIKE '%-no-overlay'
      AND f.id !~* '-designer-[0-9a-f-]{36}$'
      AND ${videoVariantSql("f")}='pipeline-final'
      AND NOT ${POINTS_AT_F}
      AND (CASE WHEN $3::text IS NULL THEN f.active_designer_revision_id IS NULL
        ELSE EXISTS (SELECT 1 FROM ${ident}.files n WHERE n.project=f.project AND n.id=$3 AND n.type='video' AND ${videoVariantSql("n")}='no-overlay') END)`;

type Tx = TransactionSql;

/**
 * Delete one row and its objects in one transaction: lock the row with all
 * guards, delete the objects, delete the row, commit. A refused row keeps its
 * objects. The step count changes only after the commit, so --stop-after
 * never rolls back a row whose objects are gone.
 */
async function guardedDelete(
  name: string, label: string, refused: string[], objectKeys: string[],
  lock: (tx: Tx) => Promise<Array<{ allowed: boolean }>>, remove: (tx: Tx) => Promise<unknown[]>,
): Promise<void> {
  const result = await sql.begin((tx) => deleteRowWithObjects({
    lock: async () => {
      const rows = await lock(tx);
      if (rows.length === 0) return "missing";
      return rows[0]!.allowed ? "ok" : "refused";
    },
    deleteObjects: async () => { for (const objectKey of objectKeys) await deleteObject(objectKey); },
    deleteRow: async () => (await remove(tx)).length === 1,
  }));
  if (result === "refused") refused.push(label);
  if (result === "deleted") count(name);
}

async function deleteOverlaid(item: OverlaidItem, refused: string[]): Promise<void> {
  const params = [item.project, item.id, item.companion_id];
  await guardedDelete(
    item.companion_id ? "overlaid_videos" : "overlaid_videos_without_no_overlay", `${item.project}/${item.id}`, refused, overlaidObjectKeys(item),
    (tx) => tx.unsafe<Array<{ allowed: boolean }>>(`
      SELECT (${OVERLAID_DELETE_GUARDS}) AS allowed
      FROM ${ident}.files f WHERE f.project=$1 AND f.id=$2 AND f.type='video'
      FOR UPDATE OF f`, params),
    (tx) => tx.unsafe(`
      DELETE FROM ${ident}.files f
      WHERE f.project=$1 AND f.id=$2 AND ${OVERLAID_DELETE_GUARDS}
      RETURNING f.id`, params),
  );
}

async function deleteSubtitle(row: SubtitleRow, refused: string[]): Promise<void> {
  await guardedDelete(
    "subtitle_files", `${row.project}/${row.id}`, refused, subtitleObjectKeys(row),
    (tx) => tx.unsafe<Array<{ allowed: boolean }>>(
      `SELECT true AS allowed FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='subtitle' FOR UPDATE`, [row.project, row.id]),
    (tx) => tx.unsafe(`DELETE FROM ${ident}.files WHERE project=$1 AND id=$2 AND type='subtitle' RETURNING id`, [row.project, row.id]),
  );
}

async function deleteLogo(projectName: string, refused: string[]): Promise<void> {
  await guardedDelete(
    "project_logos", `logo ${projectName}`, refused, [logoObjectKey(projectName)],
    (tx) => tx.unsafe<Array<{ allowed: boolean }>>(
      `SELECT true AS allowed FROM ${ident}.project_overlay_logos WHERE project=$1 FOR UPDATE`, [projectName]),
    (tx) => tx.unsafe(`DELETE FROM ${ident}.project_overlay_logos WHERE project=$1 RETURNING project`, [projectName]),
  );
}

async function runApply(): Promise<number> {
  const before = await inventory();
  printReport("plan before apply", groups(before), before.schema);

  // Step 1 and 2: in one transaction, move every designer link and active
  // pointer, and copy the approved title and the trash, pending and review
  // state of each overlaid row to its no-overlay row.
  await relinkAndMovePointers(before.plan);

  // Re-read the state. The deletes start only when no link or pointer is left to move.
  const inv = await inventory();
  if (moveWork(inv.plan) > 0) {
    throw new Error("Designer links, pointers, titles or state are still left to move. No row was deleted. Run apply again.");
  }

  // Step 3: overlaid videos. Each row is locked and guarded in a transaction
  // before its objects are deleted. A refused row keeps its objects.
  const refused: string[] = [];
  for (const item of inv.plan.overlaid_deletes) await deleteOverlaid(item, refused);

  // Step 4: SRTs, logos, remux jobs, subtitle sessions and temp objects.
  for (const row of inv.subtitles) await deleteSubtitle(row, refused);
  for (const entry of inv.subtitleOrphans) { await deleteObject(entry.key); count("subtitle_orphan_objects"); }
  for (const row of inv.logos) await deleteLogo(row.project, refused);
  for (const entry of inv.logoOrphans) { await deleteObject(entry.key); count("logo_orphan_objects"); }
  if (inv.schema.subtitle_remux_jobs_table && inv.remuxJobs.length > 0) {
    const deleted = await sql.unsafe(`DELETE FROM ${ident}.subtitle_remux_jobs WHERE ($1::text IS NULL OR project=$1) RETURNING id`, [project]);
    done.remux_jobs = deleted.length;
  }
  for (const session of inv.sessions) {
    if (session.upload_id && session.state === "active") {
      const ext = getExtensionForMime(session.mime_type) === ".bin" ? ".srt" : getExtensionForMime(session.mime_type);
      await s3.send(new AbortMultipartUploadCommand({ Bucket: bucket, Key: subtitleFileKey(session.project, session.file_id, ext), UploadId: session.upload_id })).catch(() => {});
    }
    await sql.unsafe(`DELETE FROM ${ident}.upload_sessions WHERE id=$1 AND type='subtitle'`, [session.id]);
    count("subtitle_upload_sessions");
  }
  for (const entry of inv.remuxTemps) { await deleteObject(entry.key); count("remux_temp_objects"); }
  for (const entry of inv.workerTemps) { await deleteObject(entry.key); count("worker_temp_objects"); }

  const after = await inventory();
  const afterGroups = groups(after);
  printReport("state after apply", afterGroups, after.schema);
  const blocked = after.plan.blocked_overlaid.length + refused.length;
  console.log(`SUMMARY ${JSON.stringify({ mode: "apply", project: project ?? "all-projects", done, refused, after: summary(afterGroups), schema: after.schema })}`);
  if (blocked > 0) {
    console.error(`Apply left ${after.plan.blocked_overlaid.length} blocked overlaid videos (see blocked_overlaid_videos) and refused ${refused.length} deletes because a guard failed (see refused). The refused rows keep their objects.`);
    return 3;
  }
  return 0;
}

// ---- drop-schema ------------------------------------------------------------

async function runDropSchema(): Promise<number> {
  const counts = async (q: { unsafe: typeof sql.unsafe }) => {
    const files = Number((await q.unsafe<{ n: string }[]>(`SELECT count(*)::text n FROM ${ident}.files WHERE type='subtitle'`))[0]?.n ?? 0);
    const sessions = Number((await q.unsafe<{ n: string }[]>(`SELECT count(*)::text n FROM ${ident}.upload_sessions WHERE type='subtitle'`))[0]?.n ?? 0);
    return { files, sessions };
  };
  const before = await counts(sql);
  if (before.files > 0 || before.sessions > 0) {
    throw new Refusal(`Refusing to drop the schema: ${before.files} subtitle files and ${before.sessions} subtitle upload sessions remain. Run apply first.`);
  }
  console.log(`== schema before: ${JSON.stringify(await schemaState())}`);
  await sql.begin(async (tx) => {
    await tx.unsafe(`LOCK TABLE ${ident}.files, ${ident}.upload_sessions IN ACCESS EXCLUSIVE MODE`);
    const locked = await counts(tx);
    if (locked.files > 0 || locked.sessions > 0) throw new Refusal("Refusing to drop the schema: subtitle rows came back. Run apply again.");
    await tx.unsafe(`DROP TABLE IF EXISTS ${ident}.subtitle_remux_jobs`);
    await tx.unsafe(`DROP TABLE IF EXISTS ${ident}.project_overlay_logos`);
    await tx.unsafe(`ALTER TABLE IF EXISTS ${ident}.source_processing DROP COLUMN IF EXISTS srt_text`);
    await tx.unsafe(`ALTER TABLE ${ident}.files DROP CONSTRAINT IF EXISTS files_type_check`);
    await tx.unsafe(`ALTER TABLE ${ident}.files ADD CONSTRAINT files_type_check CHECK (type IN ('audio', 'video', 'original'))`);
    await tx.unsafe(`ALTER TABLE ${ident}.upload_sessions DROP CONSTRAINT IF EXISTS upload_sessions_type_check`);
    await tx.unsafe(`ALTER TABLE ${ident}.upload_sessions ADD CONSTRAINT upload_sessions_type_check CHECK (type IN ('audio', 'video', 'original'))`);
  });
  const after = await schemaState();
  console.log(`== schema after: ${JSON.stringify(after)}`);
  console.log(`SUMMARY ${JSON.stringify({ mode: "drop-schema", schema: after })}`);
  return 0;
}

// ---- main -----------------------------------------------------------------

async function main(): Promise<number> {
  if (mode !== "dry-run" && mode !== "apply" && mode !== "drop-schema") {
    throw new Refusal("Usage: bun run scripts/no_overlay_data_move.ts <dry-run|apply|drop-schema> [--confirm] [--project=<name>] [--max-ids=<n>]");
  }
  if (mode !== "dry-run" && !confirm) throw new Refusal(`Refusing to write: ${mode} needs --confirm. Run dry-run first and review its output.`);
  if (mode === "drop-schema" && project) throw new Refusal("drop-schema changes the whole schema. Do not give --project.");
  if (!Number.isFinite(maxIds) && maxIds !== Number.POSITIVE_INFINITY) throw new Refusal("--max-ids must be a number");
  if (stopAfter !== null && (!Number.isSafeInteger(stopAfter) || stopAfter < 1)) throw new Refusal("--stop-after must be a positive integer");

  if (mode === "dry-run") {
    const inv = await inventory();
    const all = groups(inv);
    printReport("dry-run (no change)", all, inv.schema);
    console.log(`SUMMARY ${JSON.stringify({ mode, project: project ?? "all-projects", groups: summary(all), work_left: WORK_GROUPS.reduce((sum, name) => sum + (all[name]?.count ?? 0), 0), schema: inv.schema })}`);
    return 0;
  }
  if (mode === "apply") return runApply();
  return runDropSchema();
}

let code = 1;
try {
  code = await main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  if (error instanceof Refusal) { console.error(message); code = 2; }
  else if (error instanceof StopRequested) { console.error(message); console.log(`SUMMARY ${JSON.stringify({ mode, stopped: true, done })}`); code = 4; }
  else { console.error(`Error: ${message}`); code = 1; }
} finally {
  await closeDb();
}
process.exit(code);
