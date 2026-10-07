/**
 * Shared SQL fragments and rules for video rows.
 *
 * The routes and the operator scripts use this module. It has no route side
 * effects, so a script can import it without the HTTP routes.
 */

/** The tags of a row as a JSONB array. Legacy rows keep the array as a JSON string. */
export function normalizedTagsSql(alias: string): string {
  return `(CASE WHEN jsonb_typeof(${alias}.tags) = 'string' THEN (${alias}.tags #>> '{}')::jsonb ELSE ${alias}.tags END)`;
}

/**
 * The media variant of a video row. Legacy rows without the explicit column
 * use the same rules as the video tag-state migration.
 */
export function videoVariantSql(alias: string): string {
  return `COALESCE(${alias}.media_variant, CASE
    WHEN ${alias}.designer_of_id IS NOT NULL OR ${normalizedTagsSql(alias)} @> '["designer"]'::jsonb THEN 'designer'
    WHEN ${normalizedTagsSql(alias)} @> '["no-overlay"]'::jsonb OR ${alias}.id LIKE '%-no-overlay' THEN 'no-overlay'
    ELSE 'pipeline-final' END)`;
}

/* -------------------------------------------------------------------------- */
/* Legacy overlaid contract (#44). The read path in routes/files.ts and the   */
/* data move in scripts/no_overlay_data_move.ts use the same rules:           */
/*                                                                            */
/* Title rule: the card (no-overlay row) title wins. The legacy overlaid      */
/* title is used only when the card title is NULL, blank, or ends with        */
/* " (No Overlay)" (a title that the old PC pipeline made).                   */
/*                                                                            */
/* State rule: while a legacy overlaid row exists, it holds the card state    */
/* (visibility, publication_status, review_status), because it was the card   */
/* that users saw. Writes to the card also go to its legacy overlaid rows.    */
/* -------------------------------------------------------------------------- */

/** Title suffix of the no-overlay rows that the old PC pipeline made. */
export const LEGACY_NO_OVERLAY_TITLE_SUFFIX = " (No Overlay)";

/** True when the card title must give way to the legacy overlaid title. */
export function cardTitleNeedsLegacy(title: string | null | undefined): boolean {
  const trimmed = title?.trim() ?? "";
  return trimmed === "" || trimmed.endsWith(LEGACY_NO_OVERLAY_TITLE_SUFFIX);
}

/** SQL form of cardTitleNeedsLegacy for the title column of `alias`. */
export function cardTitleNeedsLegacySql(alias: string): string {
  return `(COALESCE(BTRIM(${alias}.title), '') = '' OR BTRIM(${alias}.title) LIKE '%${LEGACY_NO_OVERLAY_TITLE_SUFFIX}')`;
}

/** Effective visibility of a row: the column, else the `trash` tag. */
export function visibilitySql(alias: string): string {
  return `COALESCE(${alias}.visibility, CASE WHEN ${normalizedTagsSql(alias)} @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END)`;
}

/** Effective publication status of a video row: the column, else the `pending` tag. */
export function publicationStatusSql(alias: string): string {
  return `COALESCE(${alias}.publication_status, CASE WHEN ${normalizedTagsSql(alias)} @> '["pending"]'::jsonb THEN 'pending' ELSE 'published' END)`;
}

/**
 * WHERE predicate: `legacy` is a legacy overlaid row of the no-overlay card
 * `card`. The match is by source_id, or by the ID `<overlaid id>-no-overlay`.
 * The two probes are separate so that each one can use an index.
 */
export function legacyOverlaidMatchSql(card: string, legacy: string): string {
  return `${legacy}.project = ${card}.project
      AND ${legacy}.type = 'video'
      AND ${legacy}.id <> ${card}.id
      AND ${legacy}.designer_of_id IS NULL
      AND ${legacy}.id NOT LIKE '%-designer'
      AND ${videoVariantSql(legacy)} = 'pipeline-final'
      AND (${legacy}.source_id = ${card}.source_id
        OR (${card}.id LIKE '%-no-overlay' AND ${legacy}.id = left(${card}.id, -length('-no-overlay'))))`;
}

/**
 * ORDER BY list that picks the primary legacy overlaid row of a card: not in
 * trash first, then the newest, then the ID. The data move (preferOverlaid in
 * noOverlayDataMove.ts) uses the same order.
 */
export function legacyOverlaidOrderSql(legacy: string): string {
  return `CASE WHEN ${visibilitySql(legacy)} = 'trash' THEN 1 ELSE 0 END, ${legacy}.created_at DESC, ${legacy}.id`;
}
