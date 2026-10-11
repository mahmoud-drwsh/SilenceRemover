/**
 * Filename and file-id sanitizers - 1:1 ports of `sanitize_filename` and
 * `sanitize_file_id` in remote/app.py. Same reserved-character set and
 * 200-character limit so the two services produce the same output.
 */

const RESERVED_FILENAME_CHARS = new Set('/\\:*?"<>|');
const FORBIDDEN_CONTROL_CHARS = new Set("\u0000\n\r\t");

/**
 * Sanitize a string for use as a filesystem filename:
 * - drop control chars and reserved chars `/ \\ : * ? " < > |`
 * - collapse runs of whitespace to single spaces and trim
 * - cap at 200 characters
 */
export function sanitizeFilename(name: string | null | undefined): string {
  if (!name) return "";
  let cleaned = "";
  for (const ch of name) {
    if (FORBIDDEN_CONTROL_CHARS.has(ch)) continue;
    if (RESERVED_FILENAME_CHARS.has(ch)) continue;
    cleaned += ch;
  }
  cleaned = cleaned.split(/\s+/).filter(Boolean).join(" ").trim();
  return cleaned.slice(0, 200);
}

/**
 * Sanitize a file ID. Strips path traversal characters (`..`, `/`, `\`, NUL)
 * plus the reserved filesystem characters. Caps length at 200 characters.
 */
export function sanitizeFileId(fileId: string | null | undefined): string {
  if (!fileId) return "";
  let cleaned = fileId
    .replaceAll("..", "")
    .replaceAll("/", "")
    .replaceAll("\\", "")
    .replaceAll("\u0000", "");
  cleaned = cleaned
    .replaceAll(":", "")
    .replaceAll("*", "")
    .replaceAll("?", "")
    .replaceAll('"', "")
    .replaceAll("<", "")
    .replaceAll(">", "")
    .replaceAll("|", "");
  return cleaned.slice(0, 200);
}

/**
 * Normalize a title for comparison. Mirrors `normalize_title` in remote/app.py:
 * treat null/undefined as empty string and trim whitespace.
 */
export function normalizeTitle(title: string | null | undefined): string {
  if (title == null) return "";
  return title.trim();
}
