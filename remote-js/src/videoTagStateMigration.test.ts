import { describe, expect, test } from "bun:test";
import { buildVideoTagStatePlan, type TagStateRow } from "./videoTagStateMigration.ts";

function row(overrides: Partial<TagStateRow>): TagStateRow {
  return {
    project: "lessons", id: "clip", type: "video", tags: [], designer_of_id: null,
    active_designer_revision_id: null, media_variant: null, review_status: null,
    visibility: null, publication_status: null, ...overrides,
  };
}

describe("video tag/state migration plan", () => {
  test("removes only folder-like video tags and retains pipeline tags", () => {
    const plan = buildVideoTagStatePlan([
      row({ id: "final", tags: ["all", "FB", "TT", "YT", "custom"] }),
      row({ id: "final-no-overlay", tags: ["no-overlay"] }),
      row({ id: "pending", tags: ["pending"] }),
      row({ id: "trashed", tags: ["trash", "designer"], designer_of_id: "final" }),
      row({ id: "review", type: "audio", tags: ["todo"] }),
      row({ id: "approved", type: "audio", tags: ["ready"] }),
      row({ id: "discarded", type: "audio", tags: ["trash"] }),
    ]);

    expect(plan.rows.find((item) => item.id === "final")?.next_tags).toEqual(["custom"]);
    expect(plan.rows.find((item) => item.id === "final-no-overlay")?.next_media_variant).toBe("no-overlay");
    expect(plan.rows.find((item) => item.id === "pending")?.next_publication_status).toBe("pending");
    expect(plan.rows.find((item) => item.id === "trashed")?.next_tags).toEqual(["trash"]);
    expect(plan.rows.filter((item) => item.type === "audio").map((item) => item.next_tags)).toEqual([["ready"], ["trash"], ["todo"]]);
    expect(plan.tag_inventory.after.video).toEqual({ custom: 1, trash: 1 });
    expect(plan.tag_inventory.after.audio).toEqual({ ready: 1, trash: 1, todo: 1 });
  });

  test("backfills explicit state without changing virtual-view membership", () => {
    const plan = buildVideoTagStatePlan([
      row({ id: "final", tags: ["FB"] }),
      row({ id: "final-no-overlay", tags: ["no-overlay"] }),
      row({ id: "pending", tags: ["pending"] }),
      row({ id: "final-designer-r1", tags: ["designer"], designer_of_id: "final" }),
      row({ id: "review", type: "audio", tags: ["ready"] }),
    ]);

    expect(plan.memberships.preserved).toBe(true);
    expect(plan.memberships.internal_views_preserved).toBe(true);
    for (const difference of Object.values(plan.memberships.differences)) {
      expect(difference).toEqual({ added: [], removed: [] });
    }
    expect(plan.memberships.after["no-overlay"]!.ids).toEqual(["lessons/video/final-no-overlay"]);
    expect(plan.memberships.after.designer!.ids).toEqual(["lessons/video/final-designer-r1"]);
    expect(plan.memberships.after.pending!.ids).toEqual(["lessons/video/pending"]);
    expect(plan.memberships.after["audio-approved"]!.ids).toEqual(["lessons/audio/review"]);
    expect(plan.state_inventory.missing_before).toEqual({ media_variant: 4, review_status: 1, visibility: 5, publication_status: 4 });
    expect(plan.state_inventory.missing_after).toEqual({ media_variant: 0, review_status: 0, visibility: 0, publication_status: 0 });
  });

  test("fingerprint is deterministic and changes with source state", () => {
    const first = buildVideoTagStatePlan([row({ id: "b", tags: ["FB"] }), row({ id: "a", tags: ["pending"] })]);
    const reordered = buildVideoTagStatePlan([row({ id: "a", tags: ["pending"] }), row({ id: "b", tags: ["FB"] })]);
    const changed = buildVideoTagStatePlan([row({ id: "a", tags: ["pending"] }), row({ id: "b", tags: ["trash"] })]);
    expect(first.plan_sha256).toBe(reordered.plan_sha256);
    expect(changed.plan_sha256).not.toBe(first.plan_sha256);
  });

  test("apply binds tags as a JSON array rather than a JSON-encoded string", async () => {
    const script = await Bun.file(new URL("../scripts/rehearse_video_tag_state_migration.ts", import.meta.url)).text();
    expect(script).toContain("[row.next_tags, row.next_media_variant");
    expect(script).not.toContain("JSON.stringify(row.next_tags)");
    expect(script).toContain("ORDER BY type,id FOR UPDATE");
    expect(script).toContain("lockedPlan.plan_sha256 !== expectedFingerprint");
  });
});
