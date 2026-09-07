# Video tag/state migration runbook

This migration removes only the legacy video tags `all`, `designer`,
`no-overlay`, `pending`, `FB`, `TT`, and `YT`. It retains video `trash`, leaves
every audio tag unchanged, and fills missing explicit media state using the
existing legacy interpretation. It never changes media objects, titles, IDs,
checksums, or relationships.

## Rehearsal

From `remote-js/`, run the report for exactly one project:

```sh
bun run scripts/rehearse_video_tag_state_migration.ts --project=PROJECT
```

Save the complete JSON report. Review the before/after tag inventory, missing
state counts, and every virtual-view membership difference.
`memberships.internal_views_preserved` must be `true` before apply is allowed.
Record `plan_sha256`, then take and verify a production database backup before
applying anything.

## Apply

Apply only the exact reviewed plan:

```sh
ALLOW_VIDEO_TAG_STATE_MIGRATION=1 bun run scripts/rehearse_video_tag_state_migration.ts \
  --project=PROJECT --apply --plan-sha256=REVIEWED_SHA256
```

Apply mode opens a serializable transaction, locks and re-reads the complete
project, and recomputes the reviewed fingerprint from those locked rows. It
rejects a fingerprint mismatch or internal virtual-view membership difference;
any such failure rolls back the entire project. Tags are bound as native JSON
arrays, normalizing historical JSON-encoded-string storage.

## Verification

Run the dry-run again. Confirm:

- `changed_rows` is zero;
- removed video tags have zero assignments;
- video `trash` and all audio `todo`/`ready`/`trash` counts match the reviewed report;
- every explicit-state missing count is zero; and
- all before/after view membership differences remain empty.

Then run the application health check and manually open All, Needs Designer,
Pipeline Final, No Overlay, Designer Video, Pending, Trash, Audio Todo, and
Audio Approved.

## Recovery

There is no blind rollback command because it could overwrite legitimate edits
made after migration. If verification fails, stop writers, restore the verified
pre-apply backup into an isolated database, compare only the reported changed
rows, and prepare a reviewed row-specific recovery transaction. Media storage
does not need restoration because this migration never touches objects.
