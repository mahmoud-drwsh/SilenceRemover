export function sanitizeFilename(name: string): string {
  if (!name) return "";
  const reserved = '/\\:*?"<>|';
  let cleaned = "";
  for (const c of name) {
    if (c === "\0" || c === "\n" || c === "\r" || c === "\t") continue;
    if (reserved.includes(c)) continue;
    cleaned += c;
  }
  cleaned = cleaned.split(/\s+/).join(" ").trim();
  return cleaned.slice(0, 200);
}

export function sanitizeFileId(fileId: string): string {
  if (!fileId) return "";
  let cleaned = fileId
    .replaceAll("..", "")
    .replaceAll("/", "")
    .replaceAll("\\", "")
    .replaceAll("\0", "")
    .replaceAll(":", "")
    .replaceAll("*", "")
    .replaceAll("?", "")
    .replaceAll('"', "")
    .replaceAll("<", "")
    .replaceAll(">", "")
    .replaceAll("|", "");
  return cleaned.slice(0, 200);
}
