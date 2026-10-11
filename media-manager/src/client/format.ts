/** Display formats of the old project app. */

/** "m:ss" from seconds. Empty when there is no duration. */
export function formatDuration(seconds: number): string {
  if (!seconds) return "";
  const whole = Math.floor(seconds);
  const m = Math.floor(whole / 60);
  const s = whole % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Size with one decimal: B, KB, MB, GB. Empty for 0. */
export function formatSize(bytes: number): string {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

/** "m:ss • size • id", without the empty parts. */
export function formatMeta(parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(" • ");
}
