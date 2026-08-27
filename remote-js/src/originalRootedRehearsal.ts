import { createHash } from "node:crypto";
import { getDb, schemaIdent } from "./db.ts";

type Candidate = {
  project: string; id: string; type: string; source_id: string | null; designer_of_id: string | null; tags: unknown;
  media_variant: string | null; review_status: string | null; visibility: string | null; publication_status: string | null;
};

type Planned = {
  project: string; id: string; type: string; sourceId: string; mediaVariant: string | null;
  reviewStatus: string | null; visibility: string; publicationStatus: string | null;
};

export type OriginalRootedRehearsalReport = {
  mode: "dry-run";
  project: string;
  plan_sha256: string;
  destructive_operations: 0;
  object_operations: 0;
  candidate_rows: number;
  safe_updates: number;
  ambiguous_rows: number;
  ambiguous_sample: Array<{ id: string; type: string; reason: string }>;
};

function tagsOf(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value !== "string") return [];
  try { const parsed = JSON.parse(value); return Array.isArray(parsed) ? parsed.map(String) : []; } catch { return []; }
}

/**
 * Produces the exact guarded-backfill plan without changing metadata or storage.
 * Keeping this in the service lets production exercise the private DB connection
 * while the public route remains a report-only, media-token-authenticated seam.
 */
export async function rehearseOriginalRootedBackfill(project: string): Promise<OriginalRootedRehearsalReport> {
  const sql = getDb();
  const ident = schemaIdent();
  const candidates = await sql.unsafe<Candidate[]>(`
    SELECT f.project,f.id,f.type,f.source_id,f.designer_of_id,f.tags,f.media_variant,f.review_status,f.visibility,f.publication_status
    FROM ${ident}.files f WHERE f.type <> 'original' AND f.project=$1 ORDER BY f.type,f.id
  `, [project]);
  const planned: Planned[] = [];
  const ambiguous: Array<{ id: string; type: string; reason: string }> = [];

  for (const row of candidates) {
    const roots = await sql.unsafe<{ id: string }[]>(`
      SELECT id FROM ${ident}.files WHERE project=$1 AND type='original' AND id = ANY($2::text[])
    `, [project, [
      ...(row.source_id ? [row.source_id] : []), row.id,
      row.id.endsWith("-no-overlay") ? row.id.slice(0, -"-no-overlay".length) : "",
      row.id.endsWith("-subtitles") ? row.id.slice(0, -"-subtitles".length) : "",
    ].filter(Boolean)]);
    const directRoot = row.source_id && roots.some((root) => root.id === row.source_id);
    if (row.source_id && !directRoot) {
      ambiguous.push({ id: row.id, type: row.type, reason: "existing source_id is not an original" });
      continue;
    }
    const root = directRoot ? row.source_id : roots.length === 1 ? roots[0]!.id : null;
    if (!root) { ambiguous.push({ id: row.id, type: row.type, reason: "no unambiguous original" }); continue; }
    const tags = tagsOf(row.tags);
    const variant = row.type !== "video" ? null : row.designer_of_id ? "designer"
      : row.id.endsWith("-no-overlay") ? "no-overlay" : "pipeline-final";
    planned.push({
      project, id: row.id, type: row.type, sourceId: root, mediaVariant: row.media_variant ?? variant,
      reviewStatus: row.review_status ?? (row.type === "audio" ? (tags.includes("ready") ? "approved" : "todo") : null),
      visibility: row.visibility ?? (tags.includes("trash") ? "trash" : "active"),
      publicationStatus: row.publication_status ?? (row.type === "video" ? (tags.includes("pending") ? "pending" : "published") : null),
    });
  }
  const plan_sha256 = createHash("sha256").update(JSON.stringify({ planned, ambiguous })).digest("hex");
  return { mode: "dry-run", project, plan_sha256, destructive_operations: 0, object_operations: 0,
    candidate_rows: candidates.length, safe_updates: planned.length, ambiguous_rows: ambiguous.length,
    ambiguous_sample: ambiguous.slice(0, 25) };
}
