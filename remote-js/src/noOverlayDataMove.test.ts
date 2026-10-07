import { describe, expect, test } from "bun:test";
import {
  deleteRowWithObjects, isRemovedWorkerTempKey, isRemuxTempKey, planNoOverlayDataMove, stateCopy, videoRole, type VideoRow,
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

  test("copies the overlaid title only when the card title needs it", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s", title: "  Approved  " }),
      row({ id: "s-no-overlay", media_variant: "no-overlay", title: "Approved (No Overlay)" }),
      row({ id: "n", title: "From overlaid" }),
      row({ id: "n-no-overlay", media_variant: "no-overlay", title: null }),
      row({ id: "b", title: "From overlaid b" }),
      row({ id: "b-no-overlay", media_variant: "no-overlay", title: "   " }),
      row({ id: "t", title: "Same" }),
      row({ id: "t-no-overlay", media_variant: "no-overlay", title: "Same" }),
      row({ id: "u", title: " " }),
      row({ id: "u-no-overlay", media_variant: "no-overlay", title: "Kept (No Overlay)" }),
      // A rename after the deploy writes the card title. The move keeps it.
      row({ id: "r", title: "Old approved" }),
      row({ id: "r-no-overlay", media_variant: "no-overlay", title: "Renamed after deploy" }),
    ]);
    expect(plan.title_copies).toEqual([
      { project: "p", no_overlay_id: "s-no-overlay", overlaid_id: "s", previous: "Approved (No Overlay)", title: "Approved" },
      { project: "p", no_overlay_id: "n-no-overlay", overlaid_id: "n", previous: null, title: "From overlaid" },
      { project: "p", no_overlay_id: "b-no-overlay", overlaid_id: "b", previous: "   ", title: "From overlaid b" },
    ]);
  });

  test("prefers the overlaid row that is not in trash for title and state", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "a", source_id: "src", title: "Active", media_variant: "pipeline-final" }),
      row({ id: "b", source_id: "src", title: "Trashed", media_variant: "pipeline-final", visibility: "trash" }),
      row({ id: "src-no-overlay", source_id: "src", media_variant: "no-overlay", title: "" }),
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
    expect(plan.state_copies.map(({ project: _p, previous_tags: _t, previous: _c, ...item }) => item)).toEqual([
      {
        no_overlay_id: "s-no-overlay", overlaid_id: "s",
        before: { visibility: "active", publication_status: "published", review_status: null },
        after: { visibility: "trash", publication_status: "pending", review_status: null },
        tags: ["no-overlay", "trash"],
      },
      {
        no_overlay_id: "r-no-overlay", overlaid_id: "r",
        before: { visibility: "active", publication_status: "pending", review_status: null },
        after: { visibility: "active", publication_status: "published", review_status: "approved" },
        tags: [],
      },
    ]);
  });

  test("copies an active overlaid state over a trashed no-overlay row", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s", media_variant: "pipeline-final" }),
      row({ id: "s-no-overlay", media_variant: "no-overlay", visibility: "trash", tags: ["trash"], review_status: "approved" }),
    ]);
    expect(plan.state_copies).toEqual([{
      project: "p", no_overlay_id: "s-no-overlay", overlaid_id: "s",
      before: { visibility: "trash", publication_status: "published", review_status: "approved" },
      after: { visibility: "active", publication_status: "published", review_status: "approved" },
      previous: { visibility: "trash", publication_status: null, review_status: "approved" },
      previous_tags: ["trash"], tags: [],
    }]);
  });

  test("fixes a trash tag that does not agree with the overlaid state", () => {
    const plan = planNoOverlayDataMove([
      row({ id: "s", media_variant: "pipeline-final", visibility: "active" }),
      row({ id: "s-no-overlay", media_variant: "no-overlay", visibility: "active", tags: ["trash"] }),
    ]);
    expect(plan.state_copies.map((item) => item.tags)).toEqual([[]]);
  });

  test("a state copy is not planned again after it is applied", () => {
    const overlaid = row({ id: "s", media_variant: "pipeline-final", visibility: "trash", publication_status: "pending", review_status: "approved" });
    const first = stateCopy(overlaid, row({ id: "s-no-overlay", media_variant: "no-overlay", tags: JSON.stringify(["no-overlay"]) }))!;
    expect(first.tags).toEqual(["no-overlay", "trash"]);
    const applied = row({ id: "s-no-overlay", media_variant: "no-overlay", tags: first.tags, ...first.after });
    expect(stateCopy(overlaid, applied)).toBeNull();
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
  });
});

describe("guarded row delete", () => {
  function steps(lock: "ok" | "missing" | "refused", rowDeleted = true) {
    const calls: string[] = [];
    return {
      calls,
      steps: {
        lock: async () => { calls.push("lock"); return lock; },
        deleteObjects: async () => { calls.push("objects"); },
        deleteRow: async () => { calls.push("row"); return rowDeleted; },
      },
    };
  }

  test("deletes the objects, then the row, after the guarded lock", async () => {
    const run = steps("ok");
    expect(await deleteRowWithObjects(run.steps)).toBe("deleted");
    expect(run.calls).toEqual(["lock", "objects", "row"]);
  });

  test("a refused row keeps its objects", async () => {
    const run = steps("refused");
    expect(await deleteRowWithObjects(run.steps)).toBe("refused");
    expect(run.calls).toEqual(["lock"]);
  });

  test("a missing row deletes nothing", async () => {
    const run = steps("missing");
    expect(await deleteRowWithObjects(run.steps)).toBe("missing");
    expect(run.calls).toEqual(["lock"]);
  });

  test("a row delete that fails throws so that the transaction rolls back", async () => {
    const run = steps("ok", false);
    await expect(deleteRowWithObjects(run.steps)).rejects.toThrow("not deleted");
  });
});
