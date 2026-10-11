/**
 * The URL model of the project app (same as the old frontend/index.html):
 *
 *   /projects/<token>/<project>/<section>/<view>#admin
 *
 * - section: "audio" (default when missing), "video" or "videos" (both mean
 *   video). The app writes "videos".
 * - view: audio todo (default) | approved | trash;
 *   video all (default) | needs-designer | designer | pending | trash.
 *   The removed video view names (pipeline-final, no-overlay) open All.
 *   The app writes no view segment for All.
 * - "#admin" in the hash turns on admin mode (a client-side choice only).
 */

export type Section = "audio" | "video";

export const AUDIO_VIEWS = ["todo", "approved", "trash"] as const;
export const VIDEO_VIEWS = ["all", "needs-designer", "designer", "pending", "trash"] as const;
const REMOVED_VIDEO_VIEWS = ["pipeline-final", "no-overlay"];
/** Audio tabs that a non-admin does not see. */
const ADMIN_ONLY_AUDIO_VIEWS = ["trash"];

export const VIEW_LABELS: Record<string, string> = {
  todo: "TODO",
  approved: "Approved",
  all: "All",
  "needs-designer": "Needs Designer",
  designer: "Designer Video",
  pending: "Pending",
  trash: "Trash",
};

export type Location = {
  section: Section;
  /** The view from the URL, or null when the URL has no view segment. */
  view: string | null;
};

/** Read the section and the view from a path name. */
export function parseProjectPath(pathname: string): Location {
  const parts = pathname.split("/").filter(Boolean);
  // parts[0] = "projects", parts[1] = token, parts[2] = project.
  let raw = parts[3] ?? "audio";
  if (raw === "videos") raw = "video";
  const section: Section = raw === "video" ? "video" : "audio";
  let view = parts[4] ?? null;
  if (section === "video" && view && REMOVED_VIDEO_VIEWS.includes(view)) view = "all";
  return { section, view };
}

/** The view to show when the URL has no view. */
export function defaultView(section: Section): string {
  return section === "audio" ? "todo" : "all";
}

/**
 * A direct URL to a video view other than All or Trash opens a focused
 * queue. For an admin, tab clicks then do not change the URL (the old
 * "strict isolation"). The old code computed this from the URL that the
 * page opened or navigated to.
 */
export function isDirectViewUrl(view: string | null): boolean {
  return view !== null && view !== "all" && view !== "trash";
}

/** Path for a section and a view. The hash (for example #admin) stays. */
export function projectPath(token: string, project: string, section: Section, view: string, hash: string): string {
  let path = `/projects/${encodeURIComponent(token)}/${encodeURIComponent(project)}/${section === "video" ? "videos" : "audio"}`;
  if (view !== "all") path += `/${view}`;
  return path + hash;
}

/** The tabs that a role sees in a section. */
export function visibleTabs(section: Section, admin: boolean): readonly string[] {
  if (section === "video") return admin ? VIDEO_VIEWS : ["all"];
  return admin ? AUDIO_VIEWS : AUDIO_VIEWS.filter((view) => !ADMIN_ONLY_AUDIO_VIEWS.includes(view));
}

/**
 * True when the navigation (section switch and view tabs) is shown. A
 * non-admin in the video section sees one focused designer queue with no
 * navigation.
 */
export function showsNavigation(section: Section, admin: boolean): boolean {
  return admin || section !== "video";
}

/** Base URL of the project API. */
export function apiBase(token: string, project: string): string {
  return `/projects/${encodeURIComponent(token)}/${encodeURIComponent(project)}/api`;
}
