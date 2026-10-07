import { describe, expect, test } from "bun:test";
import {
  isLogoKey, isRemovedWorkerTempKey, isRemuxTempKey, planNoOverlayDataMove, videoRole, type VideoRow,
} from "./noOverlayDataMove.ts";

let clock = 0;
function row(overrides: Partial<VideoRow>): VideoRow {
  clock += 1;
  return {
    project: "p", id: "x", source_id: null, designer_of_id: null, active_designer_revision_id: null,
    media_variant: null, tags: [], title: null, review_status: null, visibility: null, publication_status: null, file_size: 10, mime_type: "video/mp4",
    created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, clock)), ...overrides,
  };
}

describe("video role", () => {
  test("uses the explicit variant, then legacy tags and ID suffixes", () => {
    expect(videoRole(row({ id: "s", media_variant: "pipeline-final" }))).toBe("overlaid");
    expect(videoRole(row({ id: "s" }))).toBe("overlaid");
    expect(videoRole(row({ id: "s", tags: JSON.stringify(["no-overlay"]) }))).toBe("no-overlay");
    expect(videoRole(row({ id: "s-no-overlay" }))).toBe("no-overlay");
    expect(videoRole(row({ id: "s-no-overlay", media_variant: "pipeline-final" }))).toBe("other");
    expect(videoRole(row({ id: "s-designer" }))).toBe("designer");
    expect(videoRole(row({ id: "a", designer_of_id: "s" }))).toBe("designer");
    expect(videoRole(row({ id: "a", tags: ["designer"] }))).toBe("designer");
  });
});

describe("no-overlay data move plan", () => {
  test("re-links designer revisions and keeps the explicit active pointer", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s1", source_id: "s1", media_variant: "pipeline-final", active_designer_revision_id: "d-old" }),
      row({ id: "s1-no-overlay", source_id: "s1", media_variant: "no-overlay" }),
      row({ id: "d-old", source_id: "s1", designer_of_id: "s1", media_variant: "designer" }),
      row({ id: "d-new", source_id: "s1", designer_of_id: "s1", media_variant: "designer" }),
    ]);
    expect(plan.designer_relinks.map((item) => [item.id, item.to_target])).toEqual([["d-old", "s1-no-overlay"], ["d-new", "s1-no-overlay"]]);
    expect(plan.pointer_moves).toEqual([{ project: "p", overlaid_id: "s1", no_overlay_id: "s1-no-overlay", revision_id: "d-old", implicit: false, previous: null }]);
    expect(plan.overlaid_deletes.map((item) => item.id)).toEqual(["s1"]);
    expect(plan.blocked_overlaid).toEqual([]);
  });

  test("finds the companion by overlaid ID and by shared source ID", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "final-a", source_id: "src-a" }),
      row({ id: "final-a-no-overlay", source_id: "src-a", tags: ["no-overlay"] }),
      row({ id: "final-b", source_id: "src-b" }),
      row({ id: "other-name", source_id: "src-b", media_variant: "no-overlay" }),
    ]);
    expect(plan.overlaid_deletes.map((item) => [item.id, item.companion_id])).toEqual([["final-a", "final-a-no-overlay"], ["final-b", "other-name"]]);
  });

  test("reports an ambiguous companion and does not guess", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "final", source_id: "src" }),
      row({ id: "n1", source_id: "src", media_variant: "no-overlay" }),
      row({ id: "n2", source_id: "src", media_variant: "no-overlay" }),
      row({ id: "d", designer_of_id: "final" }),
    ]);
    expect(plan.blocked_overlaid).toEqual([{ project: "p", id: "final", reason: "more than one no-overlay video matches", designer_ids: ["d"] }]);
    expect(plan.overlaid_deletes).toEqual([]);
  });

  test("converts a legacy -designer row and sets the implicit active pointer", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s2", source_id: "s2", tags: JSON.stringify(["pending"]) }),
      row({ id: "s2-no-overlay", source_id: "s2", tags: ["no-overlay"] }),
      row({ id: "s2-designer", tags: ["designer"] }),
    ]);
    expect(plan.designer_relinks).toEqual([{ project: "p", id: "s2-designer", from_target: "s2", to_target: "s2-no-overlay", legacy_suffix: true }]);
    expect(plan.pointer_moves).toEqual([{ project: "p", overlaid_id: "s2", no_overlay_id: "s2-no-overlay", revision_id: "s2-designer", implicit: true, previous: null }]);
  });

  test("gives a legacy row on a no-overlay parent an explicit target", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "n-no-overlay", media_variant: "no-overlay" }),
      row({ id: "n-no-overlay-designer" }),
    ]);
    expect(plan.designer_relinks).toEqual([{ project: "p", id: "n-no-overlay-designer", from_target: "n-no-overlay", to_target: "n-no-overlay", legacy_suffix: true }]);
  });

  test("blocks an overlaid row with a designer revision and no companion", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "lonely" }),
      row({ id: "lonely-d", designer_of_id: "lonely" }),
      row({ id: "orphan" }),
    ]);
    expect(plan.blocked_overlaid.map((item) => item.id)).toEqual(["lonely"]);
    expect(plan.overlaid_deletes.map((item) => [item.id, item.companion_id])).toEqual([["orphan", null]]);
    expect(plan.designer_relinks).toEqual([]);
  });

  test("never overwrites a pointer that the no-overlay row already has", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s", active_designer_revision_id: "d-new" }),
      row({ id: "s-no-overlay", media_variant: "no-overlay", active_designer_revision_id: "d-old" }),
      row({ id: "d-old", designer_of_id: "s-no-overlay" }),
      row({ id: "d-new", designer_of_id: "s" }),
    ]);
    expect(plan.pointer_moves).toEqual([]);
    expect(plan.pointer_conflicts.map((item) => item.kept_revision_id)).toEqual(["d-old"]);
  });

  test("copies the approved title to the no-overlay row", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s", title: "  Approved  " }),
      row({ id: "s-no-overlay", media_variant: "no-overlay", title: "Approved (No Overlay)" }),
      row({ id: "t", title: "Same" }),
      row({ id: "t-no-overlay", media_variant: "no-overlay", title: "Same" }),
      row({ id: "u", title: " " }),
      row({ id: "u-no-overlay", media_variant: "no-overlay", title: "Kept" }),
    ]);
    expect(plan.title_copies).toEqual([{ project: "p", no_overlay_id: "s-no-overlay", overlaid_id: "s", previous: "Approved (No Overlay)", title: "Approved" }]);
  });

  test("prefers the overlaid row that is not in trash for title and state", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "a", source_id: "src", title: "Active", media_variant: "pipeline-final" }),
      row({ id: "b", source_id: "src", title: "Trashed", media_variant: "pipeline-final", visibility: "trash" }),
      row({ id: "src-no-overlay", source_id: "src", media_variant: "no-overlay", title: "Old" }),
    ]);
    expect(plan.title_copies.map((item) => [item.overlaid_id, item.title])).toEqual([["a", "Active"]]);
    expect(plan.state_copies).toEqual([]);
  });

  test("copies trash, pending and review state with the matching tags", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s", tags: JSON.stringify(JSON.stringify(["trash", "pending"])) }),
      row({ id: "s-no-overlay", tags: ["no-overlay"] }),
      row({ id: "r", media_variant: "pipeline-final", review_status: "approved", publication_status: "published" }),
      row({ id: "r-no-overlay", media_variant: "no-overlay", publication_status: "pending" }),
    ]);
    expect(plan.state_copies.map(({ previous_tags: _, ...item }) => item)).toEqual([
      { project: "p", no_overlay_id: "s-no-overlay", overlaid_id: "s", visibility: "trash", publication_status: "pending", review_status: null, add_tags: ["trash", "pending"] },
      { project: "p", no_overlay_id: "r-no-overlay", overlaid_id: "r", visibility: null, publication_status: null, review_status: "approved", add_tags: [] },
    ]);
  });

  test("keeps the no-overlay pointer when it is newer", () => {
    const older = row({ id: "d-old", designer_of_id: "s" });
    const newer = row({ id: "d-new", designer_of_id: "s-no-overlay" });
    const plan = planNoOverlayDataMove([
      row({ id: "s", active_designer_revision_id: "d-old" }),
      row({ id: "s-no-overlay", media_variant: "no-overlay", active_designer_revision_id: "d-new" }),
      older, newer,
    ]);
    expect(plan.pointer_moves).toEqual([]);
    expect(plan.pointer_conflicts.map((item) => item.kept_revision_id)).toEqual(["d-new"]);
  });

  test("a plan after the move has no work left", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s1-no-overlay", source_id: "s1", media_variant: "no-overlay", active_designer_revision_id: "d" }),
      row({ id: "d", source_id: "s1", designer_of_id: "s1-no-overlay", media_variant: "designer" }),
    ]);
    expect(plan).toEqual({ designer_relinks: [], pointer_moves: [], pointer_conflicts: [], title_copies: [], state_copies: [], overlaid_deletes: [], blocked_overlaid: [], unresolved_designers: [] });
  });
});

describe("temp object keys", () => {
  test("selects only the removed worker kinds", () => {
    expect(isRemovedWorkerTempKey("source-processing/p/job/lease/subtitle")).toBe(true);
    expect(isRemovedWorkerTempKey("source-processing/p/job/lease/overlaid_video")).toBe(true);
    expect(isRemovedWorkerTempKey("source-processing/p/job/lease/review_audio")).toBe(false);
    expect(isRemovedWorkerTempKey("source-processing/p/job/lease/no_overlay_video")).toBe(false);
    expect(isRemuxTempKey("remux/p/job.mp4")).toBe(true);
    expect(isRemuxTempKey("video/p/job.mp4")).toBe(false);
    expect(isLogoKey("project-overlay-logo/my%20project.png", "my project")).toBe(true);
    expect(isLogoKey("project-overlay-logo/other.png", "my project")).toBe(false);
  });
});
