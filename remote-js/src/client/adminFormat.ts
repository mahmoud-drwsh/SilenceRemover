/** Display formats of the old admin dashboard (frontend/admin.html). */

/** "0 B", else one decimal without a trailing ".0": B, KB, MB, GB, TB. */
export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "0 B";
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), sizes.length - 1);
  return `${parseFloat((bytes / Math.pow(1024, i)).toFixed(1))} ${sizes[i]}`;
}

/** "Never", "Just now", "<n> min ago", "<n> hours ago", "<n> days ago", else the date. */
export function formatTimeAgo(timestamp: string | null, now: Date = new Date()): string {
  if (!timestamp) return "Never";
  const date = new Date(timestamp);
  const diff = Math.floor((now.getTime() - date.getTime()) / 1000);
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)} days ago`;
  return date.toLocaleDateString();
}
