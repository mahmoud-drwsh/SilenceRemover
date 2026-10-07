/**
 * Pure planning logic for the no-overlay data move (#44, #47).
 *
 * The plan reads `files` rows of type `video` and decides:
 * - which designer revisions move from an overlaid video to its no-overlay video,
 * - which active designer revision pointers move to the no-overlay video,
 * - which overlaid video rows are safe to delete, and
 * - which overlaid video rows stay because a designer revision has no new parent.
 *
 * This module does no I/O. The operator script in
 * `scripts/no_overlay_data_move.ts` reads the rows, prints the plan and applies it
 * with guarded SQL. Keep this file independent of the routes, because the routes
 * change in the same release.
 */

export const LEGACY_DESIGNER_SUFFIX = "-designer";
export const NO_OVERLAY_SUFFIX = "-no-overlay";

/** Worker temp object kinds that only the removed features made. */
export const REMOVED_WORKER_TEMP_KINDS = ["subtitle", "overlaid_video"] as const;

export interface VideoRow {
  project: string;
  id: string;
  source_id: string | null;
  designer_of_id: string | null;
  active_designer_revision_id: string | null;
  media_variant: string | null;
  tags: unknown;
  visibility: string | null;
  file_size: number | string | null;
  mime_type: string;
  created_at: Date | string | null;
}

export type VideoRole = "overlaid" | "no-overlay" | "designer" | "other";

export interface OverlaidItem {
  project: string;
  id: string;
  source_id: string | null;
  file_size: number;
  mime_type: string;
  /** The no-overlay row that takes over the card, or null when none exists. */
  companion_id: string | null;
  companion_trashed: boolean;
  /** True when more than one no-overlay row could be the companion. */
  companion_ambiguous: boolean;
}

export interface DesignerRelink {
  project: string;
  id: string;
  from_target: string;
  to_target: string;
  /** The row had no designer_of_id and used the legacy `-designer` ID suffix. */
  legacy_suffix: boolean;
}

export interface PointerMove {
  project: string;
  overlaid_id: string;
  no_overlay_id: string;
  revision_id: string;
  /** The overlaid row had no explicit pointer; the card used the newest revision. */
  implicit: boolean;
  /** The pointer that the no-overlay row has before the move. */
  previous: string | null;
}

export interface PointerConflict {
  project: string;
  overlaid_id: string;
  no_overlay_id: string;
  overlaid_revision_id: string;
  no_overlay_revision_id: string;
  kept_revision_id: string;
}

export interface BlockedOverlaid {
  project: string;
  id: string;
  reason: string;
  designer_ids: string[];
}

export interface UnresolvedDesigner {
  project: string;
  id: string;
  reason: string;
}

export interface DataMovePlan {
  designer_relinks: DesignerRelink[];
  pointer_moves: PointerMove[];
  pointer_conflicts: PointerConflict[];
  /** Overlaid rows that apply deletes (blocked rows are not in this list). */
  overlaid_deletes: OverlaidItem[];
  blocked_overlaid: BlockedOverlaid[];
  unresolved_designers: UnresolvedDesigner[];
}

export function parseTags(raw: unknown): string[] {
  let value = raw;
  // Legacy rows can keep a JSON array that is encoded as a JSON string.
  for (let depth = 0; depth < 2 && typeof value === "string"; depth += 1) {
    try { value = JSON.parse(value); } catch { return []; }
  }
  return Array.isArray(value) ? value.map(String) : [];
}

export function toBytes(value: number | string | null | undefined): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function time(value: Date | string | null): number {
  if (value === null) return 0;
  const parsed = value instanceof Date ? value.getTime() : Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function isTrashed(row: VideoRow): boolean {
  if (row.visibility === "trash") return true;
  if (row.visibility === "active") return false;
  return parseTags(row.tags).includes("trash");
}

/**
 * Classify one video row. The rules copy the read-side legacy mapping of the
 * Media Manager, with extra guards: an ID with the `-designer` or
 * `-no-overlay` suffix is never an overlaid video.
 */
export function videoRole(row: VideoRow): VideoRole {
  const tags = parseTags(row.tags);
  if (row.designer_of_id || row.media_variant === "designer" || tags.includes("designer")
    || row.id.endsWith(LEGACY_DESIGNER_SUFFIX) || /-designer-[0-9a-f-]{36}$/i.test(row.id)) {
    return "designer";
  }
  if (row.media_variant === "no-overlay") return "no-overlay";
  if (row.media_variant === "pipeline-final") {
    return row.id.endsWith(NO_OVERLAY_SUFFIX) ? "other" : "overlaid";
  }
  if (row.media_variant !== null) return "other";
  if (tags.includes("no-overlay") || row.id.endsWith(NO_OVERLAY_SUFFIX)) return "no-overlay";
  return "overlaid";
}

/**
 * The designer target of a revision: its `designer_of_id`, or the parent ID of a
 * legacy `<parent>-designer` row. Null when the row gives no target.
 */
export function designerTarget(row: VideoRow): { target: string; legacy: boolean } | null {
  if (row.designer_of_id) return { target: row.designer_of_id, legacy: false };
  if (row.id.endsWith(LEGACY_DESIGNER_SUFFIX) && row.id.length > LEGACY_DESIGNER_SUFFIX.length) {
    return { target: row.id.slice(0, -LEGACY_DESIGNER_SUFFIX.length), legacy: true };
  }
  return null;
}

/**
 * Find the no-overlay row of an overlaid row. Order:
 * 1. `<source_id>-no-overlay`, 2. `<overlaid id>-no-overlay`,
 * 3. the only no-overlay row with the same source_id (active rows first).
 */
export function resolveCompanion(
  overlaid: VideoRow,
  noOverlayByKey: Map<string, VideoRow>,
  noOverlayBySource: Map<string, VideoRow[]>,
): { row: VideoRow | null; ambiguous: boolean } {
  const exactIds = [
    ...(overlaid.source_id ? [`${overlaid.source_id}${NO_OVERLAY_SUFFIX}`] : []),
    `${overlaid.id}${NO_OVERLAY_SUFFIX}`,
  ];
  for (const id of exactIds) {
    const row = noOverlayByKey.get(key(overlaid.project, id));
    if (row) return { row, ambiguous: false };
  }
  if (!overlaid.source_id) return { row: null, ambiguous: false };
  const siblings = noOverlayBySource.get(key(overlaid.project, overlaid.source_id)) ?? [];
  const active = siblings.filter((row) => !isTrashed(row));
  if (active.length === 1) return { row: active[0]!, ambiguous: false };
  if (active.length > 1) return { row: null, ambiguous: true };
  if (siblings.length === 1) return { row: siblings[0]!, ambiguous: false };
  return { row: null, ambiguous: siblings.length > 1 };
}

function key(project: string, id: string): string {
  return `${project}\u0000${id}`;
}

/** Build the full plan from the current `files` video rows. */
export function planNoOverlayDataMove(videos: VideoRow[]): DataMovePlan {
  const byKey = new Map<string, VideoRow>();
  const noOverlayByKey = new Map<string, VideoRow>();
  const noOverlayBySource = new Map<string, VideoRow[]>();
  const overlaidRows: VideoRow[] = [];
  const designerRows: VideoRow[] = [];
  for (const row of videos) {
    byKey.set(key(row.project, row.id), row);
    const role = videoRole(row);
    if (role === "overlaid") overlaidRows.push(row);
    else if (role === "designer") designerRows.push(row);
    else if (role === "no-overlay") {
      noOverlayByKey.set(key(row.project, row.id), row);
      if (row.source_id) {
        const list = noOverlayBySource.get(key(row.project, row.source_id)) ?? [];
        list.push(row);
        noOverlayBySource.set(key(row.project, row.source_id), list);
      }
    }
  }

  const companions = new Map<string, OverlaidItem>();
  for (const row of overlaidRows) {
    const companion = resolveCompanion(row, noOverlayByKey, noOverlayBySource);
    companions.set(key(row.project, row.id), {
      project: row.project,
      id: row.id,
      source_id: row.source_id,
      file_size: toBytes(row.file_size),
      mime_type: row.mime_type,
      companion_id: companion.row?.id ?? null,
      companion_trashed: companion.row ? isTrashed(companion.row) : false,
      companion_ambiguous: companion.ambiguous,
    });
  }

  const designer_relinks: DesignerRelink[] = [];
  const unresolved_designers: UnresolvedDesigner[] = [];
  const blockers = new Map<string, string[]>();
  // Designer revisions of each overlaid row, before the move. The card uses
  // them to find the implicit active designer video.
  const revisionsOfOverlaid = new Map<string, VideoRow[]>();
  for (const row of designerRows) {
    const target = designerTarget(row);
    if (!target) {
      unresolved_designers.push({ project: row.project, id: row.id, reason: "no designer target" });
      continue;
    }
    const targetKey = key(row.project, target.target);
    const overlaid = companions.get(targetKey);
    if (overlaid) {
      const list = revisionsOfOverlaid.get(targetKey) ?? [];
      list.push(row);
      revisionsOfOverlaid.set(targetKey, list);
      if (overlaid.companion_id) {
        designer_relinks.push({ project: row.project, id: row.id, from_target: target.target, to_target: overlaid.companion_id, legacy_suffix: target.legacy });
      } else {
        const list2 = blockers.get(targetKey) ?? [];
        list2.push(row.id);
        blockers.set(targetKey, list2);
      }
      continue;
    }
    if (target.legacy && noOverlayByKey.has(targetKey)) {
      // A legacy row on a no-overlay parent gets an explicit designer target.
      designer_relinks.push({ project: row.project, id: row.id, from_target: target.target, to_target: target.target, legacy_suffix: true });
      continue;
    }
    if (!byKey.has(targetKey)) {
      unresolved_designers.push({ project: row.project, id: row.id, reason: "designer target does not exist" });
    }
  }

  const pointer_moves: PointerMove[] = [];
  const pointer_conflicts: PointerConflict[] = [];
  const blocked_overlaid: BlockedOverlaid[] = [];
  const overlaid_deletes: OverlaidItem[] = [];
  // The pointer of each no-overlay row as the plan changes it.
  const pointers = new Map<string, string | null>();
  for (const row of overlaidRows) {
    const rowKey = key(row.project, row.id);
    const item = companions.get(rowKey)!;
    const revisions = revisionsOfOverlaid.get(rowKey) ?? [];
    const blockingDesigners = blockers.get(rowKey) ?? [];
    if (!item.companion_id) {
      if (blockingDesigners.length > 0 || row.active_designer_revision_id) {
        blocked_overlaid.push({
          project: row.project,
          id: row.id,
          reason: item.companion_ambiguous ? "more than one no-overlay video matches" : "no no-overlay video exists",
          designer_ids: blockingDesigners.length > 0 ? blockingDesigners : [row.active_designer_revision_id!],
        });
        continue;
      }
      overlaid_deletes.push(item);
      continue;
    }
    overlaid_deletes.push(item);

    let revisionId = row.active_designer_revision_id;
    let implicit = false;
    if (!revisionId) {
      const newest = revisions
        .filter((revision) => !isTrashed(revision))
        .sort((a, b) => time(b.created_at) - time(a.created_at) || a.id.localeCompare(b.id))[0];
      revisionId = newest?.id ?? null;
      implicit = true;
    }
    if (!revisionId) continue;
    const companionKey = key(row.project, item.companion_id);
    const current = pointers.has(companionKey)
      ? pointers.get(companionKey)!
      : byKey.get(companionKey)?.active_designer_revision_id ?? null;
    if (current === revisionId) continue;
    if (current) {
      // A designer upload after the deploy sets the pointer on the no-overlay
      // row. The newest revision stays active, as for any designer upload.
      const currentTime = time(byKey.get(key(row.project, current))?.created_at ?? null);
      const movedTime = time(byKey.get(key(row.project, revisionId))?.created_at ?? null);
      const kept = movedTime > currentTime ? revisionId : current;
      pointer_conflicts.push({ project: row.project, overlaid_id: row.id, no_overlay_id: item.companion_id, overlaid_revision_id: revisionId, no_overlay_revision_id: current, kept_revision_id: kept });
      if (kept === current) continue;
    }
    pointer_moves.push({ project: row.project, overlaid_id: row.id, no_overlay_id: item.companion_id, revision_id: revisionId, implicit, previous: current });
    pointers.set(companionKey, revisionId);
  }

  return { designer_relinks, pointer_moves, pointer_conflicts, overlaid_deletes, blocked_overlaid, unresolved_designers };
}

/** S3 key of a `files` row. The layout is `<type>/<project>/<id><ext>`. */
export function fileObjectKey(type: "video" | "subtitle", project: string, id: string, ext: string): string {
  return `${type}/${project}/${id}${ext}`;
}

export function logoObjectKey(project: string): string {
  return `project-overlay-logo/${encodeURIComponent(project)}.png`;
}

/** Prefix of the subtitle remux temp objects (`remux/<project>/<job>.mp4`). */
export function remuxTempPrefix(project: string | null): string {
  return project ? `remux/${project}/` : "remux/";
}

/** Prefix of the worker temp objects (`source-processing/<project>/<job>/<lease>/<kind>`). */
export function workerTempPrefix(project: string | null): string {
  return project ? `source-processing/${project}/` : "source-processing/";
}

export function subtitlePrefix(project: string | null): string {
  return project ? `subtitle/${project}/` : "subtitle/";
}

export function logoPrefix(): string {
  return "project-overlay-logo/";
}

/** True only for a worker temp object of the subtitle or overlaid kind. */
export function isRemovedWorkerTempKey(objectKey: string): boolean {
  const match = /^source-processing\/[^/]+\/[^/]+\/[^/]+\/([^/]+)$/.exec(objectKey);
  return Boolean(match && (REMOVED_WORKER_TEMP_KINDS as readonly string[]).includes(match[1]!));
}

export function isRemuxTempKey(objectKey: string): boolean {
  return /^remux\/[^/]+\/[^/]+$/.test(objectKey);
}

export function isSubtitleKey(objectKey: string): boolean {
  return /^subtitle\/[^/]+\/[^/]+$/.test(objectKey);
}

export function isLogoKey(objectKey: string, project: string | null): boolean {
  if (!/^project-overlay-logo\/[^/]+\.png$/.test(objectKey)) return false;
  return project === null || objectKey === logoObjectKey(project);
}
