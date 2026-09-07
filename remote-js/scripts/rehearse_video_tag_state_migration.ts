/** Guarded report-first removal of folder-like video tags. */
import { closeDb, ensureDatabaseReady, getDb, schemaIdent } from "../src/db.ts";
import { buildVideoTagStatePlan, type TagStateRow } from "../src/videoTagStateMigration.ts";

const apply = process.argv.includes("--apply");
const project = process.argv.find((arg) => arg.startsWith("--project="))?.slice("--project=".length);
const expectedFingerprint = process.argv.find((arg) => arg.startsWith("--plan-sha256="))?.slice("--plan-sha256=".length);
if (!project) throw new Error("Refusing to run without an exact --project=… scope");
if (apply && (!expectedFingerprint || process.env.ALLOW_VIDEO_TAG_STATE_MIGRATION !== "1")) {
  throw new Error("Refusing to write: --apply needs --plan-sha256=… and ALLOW_VIDEO_TAG_STATE_MIGRATION=1");
}

await ensureDatabaseReady();
const sql = getDb();
const ident = schemaIdent();
try {
  const input = await sql.unsafe<TagStateRow[]>(`
    SELECT project,id,type,tags,designer_of_id,active_designer_revision_id,
           media_variant,review_status,visibility,publication_status
      FROM ${ident}.files WHERE project=$1 ORDER BY type,id
  `, [project]);
  const plan = buildVideoTagStatePlan(input);
  if (apply && !plan.memberships.internal_views_preserved) throw new Error("Refusing to write: planned internal virtual-view membership changed");
  if (apply) {
    if (expectedFingerprint !== plan.plan_sha256) throw new Error("Refusing to write: reviewed plan fingerprint no longer matches database state");
    await sql.begin(async (tx) => {
      await tx.unsafe("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE");
      // Lock and re-plan the full project inside the write transaction. This
      // is stronger and more portable than comparing nullable JSON/text
      // columns one parameter at a time in every UPDATE predicate.
      const lockedInput = await tx.unsafe<TagStateRow[]>(`
        SELECT project,id,type,tags,designer_of_id,active_designer_revision_id,
               media_variant,review_status,visibility,publication_status
          FROM ${ident}.files WHERE project=$1 ORDER BY type,id FOR UPDATE
      `, [project]);
      const lockedPlan = buildVideoTagStatePlan(lockedInput);
      if (lockedPlan.plan_sha256 !== expectedFingerprint) throw new Error("Concurrent change detected: locked project plan no longer matches reviewed fingerprint");
      if (!lockedPlan.memberships.internal_views_preserved) throw new Error("Concurrent change altered planned internal virtual-view membership");
      for (const row of lockedPlan.changed) {
        const updated = await tx.unsafe<{ id: string }[]>(`
          UPDATE ${ident}.files
             SET tags=$1::jsonb,
                 media_variant=COALESCE(media_variant,$2),
                 review_status=COALESCE(review_status,$3),
                 visibility=COALESCE(visibility,$4),
                 publication_status=COALESCE(publication_status,$5)
           WHERE project=$6 AND id=$7 AND type=$8
          RETURNING id
        `, [row.next_tags, row.next_media_variant, row.next_review_status,
          row.next_visibility, row.next_publication_status, row.project, row.id, row.type]);
        if (updated.length !== 1) throw new Error(`Locked row disappeared for ${row.type}/${row.id}`);
      }
    });
  }
  console.log(JSON.stringify({
    mode: apply ? "apply" : "dry-run", project, plan_sha256: plan.plan_sha256,
    candidate_rows: plan.rows.length, changed_rows: plan.changed.length,
    removed_video_tags: ["all", "designer", "no-overlay", "pending", "FB", "TT", "YT"],
    retained_tags: { video: ["trash"], audio: ["todo", "ready", "trash"] },
    tag_inventory: plan.tag_inventory, state_inventory: plan.state_inventory,
    memberships: plan.memberships,
  }, null, 2));
} finally {
  await closeDb();
}
