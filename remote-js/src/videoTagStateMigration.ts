import { createHash } from "node:crypto";

export const REMOVED_VIDEO_TAGS = new Set(["all", "designer", "no-overlay", "pending", "FB", "TT", "YT"]);

export type TagStateRow = {
  project: string;
  id: string;
  type: string;
  tags: unknown;
  designer_of_id: string | null;
  active_designer_revision_id: string | null;
  media_variant: string | null;
  review_status: string | null;
  visibility: string | null;
  publication_status: string | null;
};

export type PlannedTagStateRow = TagStateRow & {
  next_tags: string[];
  next_media_variant: string | null;
  next_review_status: string | null;
  next_visibility: string;
  next_publication_status: string | null;
};

const VIEW_NAMES = ["all", "needs-designer", "pipeline-final", "no-overlay", "designer", "pending", "trash", "audio-todo", "audio-approved", "audio-trash"] as const;
type ViewName = typeof VIEW_NAMES[number];
type Membership = Record<ViewName, string[]>;

export function tagsOf(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value !== "string") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function explicitOrLegacy(row: TagStateRow): PlannedTagStateRow {
  const tags = tagsOf(row.tags);
  const legacyVariant = row.type !== "video" ? null
    : row.designer_of_id || tags.includes("designer") ? "designer"
      : tags.includes("no-overlay") || row.id.endsWith("-no-overlay") ? "no-overlay"
        : "pipeline-final";
  const legacyReview = row.type === "audio" ? (tags.includes("ready") ? "approved" : "todo") : null;
  const legacyPublication = row.type === "video" ? (tags.includes("pending") ? "pending" : "published") : null;
  return {
    ...row,
    next_tags: row.type === "video" ? tags.filter((tag) => !REMOVED_VIDEO_TAGS.has(tag)) : tags,
    next_media_variant: row.media_variant ?? legacyVariant,
    next_review_status: row.review_status ?? legacyReview,
    next_visibility: row.visibility ?? (tags.includes("trash") ? "trash" : "active"),
    next_publication_status: row.publication_status ?? legacyPublication,
  };
}

function membership(rows: PlannedTagStateRow[], next: boolean): Membership {
  const result: Membership = {
    all: [], "needs-designer": [], "pipeline-final": [], "no-overlay": [], designer: [], pending: [], trash: [],
    "audio-todo": [], "audio-approved": [], "audio-trash": [],
  };
  const activeDesignerTargets = new Set(rows.filter((row) => {
    const visibility = next ? row.next_visibility : (row.visibility ?? (tagsOf(row.tags).includes("trash") ? "trash" : "active"));
    const variant = next ? row.next_media_variant : (row.media_variant ?? (row.designer_of_id || tagsOf(row.tags).includes("designer") ? "designer" : tagsOf(row.tags).includes("no-overlay") || row.id.endsWith("-no-overlay") ? "no-overlay" : row.type === "video" ? "pipeline-final" : null));
    return row.type === "video" && visibility === "active" && variant === "designer" && row.designer_of_id;
  }).map((row) => row.designer_of_id!));

  for (const row of rows) {
    const tags = next ? row.next_tags : tagsOf(row.tags);
    const visibility = next ? row.next_visibility : (row.visibility ?? (tags.includes("trash") ? "trash" : "active"));
    const variant = next ? row.next_media_variant : (row.media_variant ?? (row.type !== "video" ? null : row.designer_of_id || tags.includes("designer") ? "designer" : tags.includes("no-overlay") || row.id.endsWith("-no-overlay") ? "no-overlay" : "pipeline-final"));
    const review = next ? row.next_review_status : (row.review_status ?? (row.type === "audio" ? (tags.includes("ready") ? "approved" : "todo") : null));
    const publication = next ? row.next_publication_status : (row.publication_status ?? (row.type === "video" ? (tags.includes("pending") ? "pending" : "published") : null));
    const key = `${row.project}/${row.type}/${row.id}`;
    if (row.type === "video") {
      if (visibility === "trash") result.trash.push(key);
      if (visibility === "active" && variant === "pipeline-final") {
        result.all.push(key); result["pipeline-final"].push(key);
        if (!row.active_designer_revision_id && !activeDesignerTargets.has(row.id)) result["needs-designer"].push(key);
      }
      if (visibility === "active" && variant === "no-overlay") result["no-overlay"].push(key);
      if (visibility === "active" && variant === "designer") result.designer.push(key);
      if (visibility === "active" && publication === "pending") result.pending.push(key);
    } else if (row.type === "audio") {
      if (visibility === "trash") result["audio-trash"].push(key);
      else if (review === "approved") result["audio-approved"].push(key);
      else result["audio-todo"].push(key);
    }
  }
  for (const ids of Object.values(result)) ids.sort();
  return result;
}

function tagInventory(rows: PlannedTagStateRow[], next: boolean): Record<string, Record<string, number>> {
  const inventory: Record<string, Record<string, number>> = {};
  for (const row of rows) {
    const byType = inventory[row.type] ??= {};
    for (const tag of next ? row.next_tags : tagsOf(row.tags)) byType[tag] = (byType[tag] ?? 0) + 1;
  }
  return inventory;
}

function countValues(values: Array<string | null>): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const value of values) {
    const key = value ?? "<null>";
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

function stateValues(rows: PlannedTagStateRow[], next: boolean) {
  return {
    media_variant: countValues(rows.filter((row) => row.type === "video").map((row) => next ? row.next_media_variant : row.media_variant)),
    review_status: countValues(rows.filter((row) => row.type === "audio").map((row) => next ? row.next_review_status : row.review_status)),
    visibility: countValues(rows.map((row) => next ? row.next_visibility : row.visibility)),
    publication_status: countValues(rows.filter((row) => row.type === "video").map((row) => next ? row.next_publication_status : row.publication_status)),
  };
}

export function buildVideoTagStatePlan(input: TagStateRow[]) {
  const rows = [...input].sort((a, b) => {
    const left = `${a.project}\0${a.type}\0${a.id}`;
    const right = `${b.project}\0${b.type}\0${b.id}`;
    return left < right ? -1 : left > right ? 1 : 0;
  }).map(explicitOrLegacy);
  const before = membership(rows, false);
  const after = membership(rows, true);
  const membership_differences = Object.fromEntries(VIEW_NAMES.map((view) => [view, {
    added: after[view]!.filter((id) => !before[view]!.includes(id)),
    removed: before[view]!.filter((id) => !after[view]!.includes(id)),
  }]));
  const internalPreserved = VIEW_NAMES.every((view) => membership_differences[view]!.added.length === 0 && membership_differences[view]!.removed.length === 0);
  const changed = rows.filter((row) => JSON.stringify(tagsOf(row.tags)) !== JSON.stringify(row.next_tags)
    || row.media_variant !== row.next_media_variant || row.review_status !== row.next_review_status
    || row.visibility !== row.next_visibility || row.publication_status !== row.next_publication_status);
  const fingerprintRows = rows.map((row) => ({
    project: row.project, id: row.id, type: row.type, tags: tagsOf(row.tags),
    designer_of_id: row.designer_of_id, active_designer_revision_id: row.active_designer_revision_id,
    media_variant: row.media_variant, review_status: row.review_status, visibility: row.visibility,
    publication_status: row.publication_status, next_tags: row.next_tags,
    next_media_variant: row.next_media_variant, next_review_status: row.next_review_status,
    next_visibility: row.next_visibility, next_publication_status: row.next_publication_status,
  }));
  const plan_sha256 = createHash("sha256").update(JSON.stringify(fingerprintRows)).digest("hex");
  return {
    rows, changed, plan_sha256,
    tag_inventory: { before: tagInventory(rows, false), after: tagInventory(rows, true) },
    state_inventory: {
      rows: rows.length,
      before: stateValues(rows, false),
      after: stateValues(rows, true),
      missing_before: {
        media_variant: rows.filter((row) => row.type === "video" && row.media_variant === null).length,
        review_status: rows.filter((row) => row.type === "audio" && row.review_status === null).length,
        visibility: rows.filter((row) => row.visibility === null).length,
        publication_status: rows.filter((row) => row.type === "video" && row.publication_status === null).length,
      },
      missing_after: { media_variant: 0, review_status: 0, visibility: 0, publication_status: 0 },
    },
    memberships: {
      before: Object.fromEntries(Object.entries(before).map(([view, ids]) => [view, { count: ids.length, ids }])),
      after: Object.fromEntries(Object.entries(after).map(([view, ids]) => [view, { count: ids.length, ids }])),
      differences: membership_differences,
      internal_views_preserved: internalPreserved,
      preserved: internalPreserved,
    },
  };
}
