/**
 * Non-destructive rehearsal for the original-rooted media contract.
 *
 * Default mode only prints a JSON report. --apply is deliberately guarded and
 * only fills empty link/state columns; it never deletes rows, objects, tags,
 * IDs, titles, or checksums.
 */
import { createHash } from "node:crypto";
import { ensureDatabaseReady, getDb, schemaIdent } from "../src/db.ts";

const apply = process.argv.includes("--apply");
const projectArg = process.argv.find((arg) => arg.startsWith("--project="))?.slice("--project=".length);
const planArg = process.argv.find((arg) => arg.startsWith("--plan-sha256="))?.slice("--plan-sha256=".length);
if (apply && (!projectArg || !planArg || process.env.ALLOW_ORIGINAL_ROOTED_BACKFILL !== "1")) {
  throw new Error("Refusing to write: --apply needs --project=…, --plan-sha256=… and ALLOW_ORIGINAL_ROOTED_BACKFILL=1");
}

await ensureDatabaseReady();
const sql = getDb();
const ident = schemaIdent();

// A link is safe only when it resolves to an existing original in the same
// project. Ambiguous rows remain unchanged for a human decision.
const candidates = await sql.unsafe<{
  project: string; id: string; type: string; source_id: string | null; designer_of_id: string | null; tags: unknown;
  media_variant: string | null; review_status: string | null; visibility: string | null; publication_status: string | null;
}[]>(`
  SELECT f.project,f.id,f.type,f.source_id,f.designer_of_id,f.tags,f.media_variant,f.review_status,f.visibility,f.publication_status
  FROM ${ident}.files f
  WHERE f.type <> 'original' AND ($1::text IS NULL OR f.project=$1)
  ORDER BY f.project,f.type,f.id
`, [projectArg ?? null]);

type Planned = { project: string; id: string; type: string; sourceId: string; mediaVariant: string | null; reviewStatus: string | null; visibility: string; publicationStatus: string | null };
const planned: Planned[] = [];
const ambiguous: Array<{ project: string; id: string; type: string; reason: string }> = [];
let alreadyLinked = 0;
let newlyLinked = 0;
let stateOnly = 0;
let projected = 0;

for (const row of candidates) {
  let tags: string[] = Array.isArray(row.tags) ? row.tags.map(String) : [];
  if (typeof row.tags === "string") {
    try { const parsed = JSON.parse(row.tags); tags = Array.isArray(parsed) ? parsed.map(String) : []; } catch { tags = []; }
  }
  const roots = await sql.unsafe<{ id: string }[]>(`
    SELECT id FROM ${ident}.files
    WHERE project=$1 AND type='original' AND id = ANY($2::text[])
  `, [row.project, [
    ...(row.source_id ? [row.source_id] : []),
    row.id,
    row.id.endsWith("-no-overlay") ? row.id.slice(0, -"-no-overlay".length) : "",
    row.id.endsWith("-subtitles") ? row.id.slice(0, -"-subtitles".length) : "",
  ].filter(Boolean)]);
  const directRoot = row.source_id && roots.some((root) => root.id === row.source_id);
  if (row.source_id && !directRoot) {
    ambiguous.push({ project: row.project, id: row.id, type: row.type, reason: "existing source_id is not an original" });
    continue;
  }
  const root = directRoot ? row.source_id : roots.length === 1 ? roots[0]!.id : null;
  if (!root) {
    ambiguous.push({ project: row.project, id: row.id, type: row.type, reason: "no unambiguous original" });
    continue;
  }
  const variant = row.type !== "video" ? null : row.designer_of_id ? "designer"
    : row.id.endsWith("-no-overlay") ? "no-overlay" : "pipeline-final";
  const reviewStatus = row.type === "audio" ? (tags.includes("ready") ? "approved" : "todo") : null;
  const publicationStatus = row.type === "video" ? (tags.includes("pending") ? "pending" : "published") : null;
  const stateWouldChange = (variant !== null && row.media_variant === null)
    || (reviewStatus !== null && row.review_status === null)
    || row.visibility === null
    || (publicationStatus !== null && row.publication_status === null);
  if (directRoot) alreadyLinked += 1; else newlyLinked += 1;
  if (stateWouldChange && directRoot) stateOnly += 1;
  if (!directRoot || stateWouldChange) projected += 1;
  planned.push({
    project: row.project, id: row.id, type: row.type, sourceId: root,
    mediaVariant: row.media_variant ?? variant,
    reviewStatus: row.review_status ?? reviewStatus,
    visibility: row.visibility ?? (tags.includes("trash") ? "trash" : "active"),
    publicationStatus: row.publication_status ?? publicationStatus,
  });
}

const planSha256 = createHash("sha256").update(JSON.stringify({ planned, ambiguous })).digest("hex");
const report = {
  mode: apply ? "apply" : "dry-run",
  project: projectArg ?? "all-projects",
  plan_sha256: planSha256,
  destructive_operations: 0,
  object_operations: 0,
  candidate_rows: candidates.length,
  already_linked_rows: alreadyLinked,
  newly_linked_rows: newlyLinked,
  state_only_update_rows: stateOnly,
  projected_update_rows: projected,
  already_compliant_rows: planned.length - projected,
  safe_updates: planned.length,
  ambiguous_rows: ambiguous.length,
  ambiguous_sample: ambiguous.slice(0, 25),
};

if (apply) {
  if (planArg !== planSha256) throw new Error("Refusing to write: reviewed plan fingerprint no longer matches this database state");
  await sql.begin(async (tx) => {
    for (const row of planned) {
      await tx.unsafe(`
        UPDATE ${ident}.files
        SET source_id=COALESCE(source_id,$1), media_variant=COALESCE(media_variant,$2),
            review_status=COALESCE(review_status,$3), visibility=COALESCE(visibility,$4),
            publication_status=COALESCE(publication_status,$5)
        WHERE project=$6 AND id=$7 AND type=$8 AND (source_id IS NULL OR source_id=$1)
      `, [row.sourceId, row.mediaVariant, row.reviewStatus, row.visibility, row.publicationStatus, row.project, row.id, row.type]);
    }
  });
}
console.log(JSON.stringify(report, null, 2));
