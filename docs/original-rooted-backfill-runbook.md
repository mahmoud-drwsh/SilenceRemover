# Original-rooted backfill runbook

This runbook repairs only **provably linked** derived-media metadata. It never
deletes a `files` row, an R2 object, a tag, title, checksum, or ID.

## Preconditions

1. Run the dry-run script in the service container for exactly one project.
2. Review the report: `newly_linked_rows`, `state_only_update_rows`,
   `already_compliant_rows`, and `ambiguous_rows` must be understood.
3. Record the reported `plan_sha256`, take a database backup, and confirm that
   ambiguous rows will remain unchanged.
4. Run the apply command only with that exact fingerprint and
   `ALLOW_ORIGINAL_ROOTED_BACKFILL=1`.

The apply command recomputes the plan before opening its transaction. A changed
row makes the fingerprint mismatch and the command exits without writing.
Within the transaction, every assignment is `COALESCE`: only empty
`source_id`/explicit-state columns can be filled. Existing values are never
replaced.

## Validation

After apply, run the dry-run again. It must report:

- zero destructive and object operations;
- the same candidate and unresolved counts, unless concurrent legitimate
  uploads occurred; and
- no invalid original links.

Also check `/healthz` and retain the dry-run/apply logs with the database
backup reference.

## Rollback

There is intentionally no blind automated rollback. Clearing links or explicit
state without a pre-apply manifest could erase a later pipeline or human edit.

If a confirmed bad update requires recovery:

1. Stop writers for the affected project and take a fresh database backup.
2. Restore the pre-apply database backup into an isolated database.
3. Compare only the affected `files` rows to identify columns that were empty
   before the backfill.
4. Apply a reviewed, row-specific inverse update in one transaction, guarded
   by project, ID, type, and the exact current value written by the backfill.
5. Re-run the dry-run and verify R2 object counts; no R2 rollback is required
   because this backfill never writes objects.

For ambiguous or missing-Original rows, do not attempt rollback or repair in
this runbook. Track them in a dedicated recovery issue.
