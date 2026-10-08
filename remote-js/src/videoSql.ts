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

/** Effective visibility of a row: the column, else the `trash` tag. */
export function visibilitySql(alias: string): string {
  return `COALESCE(${alias}.visibility, CASE WHEN ${normalizedTagsSql(alias)} @> '["trash"]'::jsonb THEN 'trash' ELSE 'active' END)`;
}

/** Effective publication status of a video row: the column, else the `pending` tag. */
export function publicationStatusSql(alias: string): string {
  return `COALESCE(${alias}.publication_status, CASE WHEN ${normalizedTagsSql(alias)} @> '["pending"]'::jsonb THEN 'pending' ELSE 'published' END)`;
}
