# No-overlay data move runbook

This runbook removes the stored output of the removed features (#44, #47, #49).
It moves the designer links to the no-overlay video. Then it deletes the
overlaid videos, the SRT files, the project logo, the remux jobs, the subtitle
upload sessions and the temp objects of the removed kinds. Last, it removes the
old schema.

The command is `remote-js/scripts/no_overlay_data_move.ts`. It has three modes:

| Mode | Changes | Needs `--confirm` |
| --- | --- | --- |
| `dry-run` | Nothing. It reads the database and the object store. | No |
| `apply` | Rows and objects. The tables stay. | Yes |
| `drop-schema` | Schema only. | Yes |

The command never deletes an original, a no-overlay video, a review audio or a
designer revision. It prints no credentials and no presigned URLs.

## Order

1. Deploy the code of #44. Do the normal deploy checks first: 0 active upload
   sessions, no `ffmpeg` process in the worker, then `/healthz` is OK.
2. Run `dry-run`. Keep the output.
3. Get the operator approval for the dry-run output.
4. Make a database backup.
5. Run `apply`.
6. Run `dry-run` again. Make sure that no work is left.
7. Run `drop-schema` only when the deployed startup code does not create the
   old tables and the `subtitle` type again (#49). Otherwise the next restart
   adds them back.

## Find the container

Run these commands on the server host. Find the Media Manager service container
by its name or image:

```sh
docker ps --format '{{.Names}}\t{{.Image}}'
container=<name of the Media Manager container>
```

The command uses the service environment in that container. Do not copy the
environment out of the container.

## Dry-run

```sh
docker exec "$container" bun run scripts/no_overlay_data_move.ts dry-run > no-overlay-dry-run.log
tail -n 1 no-overlay-dry-run.log
```

Each group shows `count`, `bytes` and one line for each ID. Use
`--max-ids=<n>` to show fewer IDs. Use `--project=<name>` to read one project.
The last line starts with `SUMMARY` and has the counts and bytes as JSON.

Examine these groups before approval:

- `designer_relinks` and `active_pointer_moves`: the designer links to move.
- `overlaid_videos`: all overlaid videos to delete.
  `overlaid_videos_without_no_overlay` shows the ones with no no-overlay video.
  This loss cannot be undone.
- `blocked_overlaid_videos`: overlaid videos that stay, because a designer
  revision points at them and no no-overlay video exists. Apply does not
  delete them. Decide about each one by hand.
- `pointer_conflicts`: the no-overlay video already has an active designer
  revision. Apply does not overwrite it.
- `title_copies`: the approved title of the overlaid video goes to the
  no-overlay video. Old PC no-overlay videos have the title `<title> (No Overlay)`.
- `state_copies`: the overlaid video is in trash, pending or has a review
  state, and the no-overlay video does not. Apply copies this state and the
  matching `trash` and `pending` tags to the no-overlay video.
- `overlaid_videos_with_trashed_no_overlay`: after the move, these cards are in
  the trash.
- `unresolved_designers`: designer revisions with no clear target. Apply does
  not change them.

## Apply

```sh
docker exec "$container" bun run scripts/no_overlay_data_move.ts apply --confirm > no-overlay-apply.log
echo "exit code: $?"
```

Apply does the steps in this order:

1. In one transaction, it moves each designer link to the no-overlay video. It
   gives each legacy `-designer` row an explicit designer target. It moves each
   active designer revision pointer to the no-overlay video, but it does not
   overwrite a pointer that is already set. It copies the approved title and
   the trash, pending and review state to the no-overlay video.
2. It reads the database again. It starts to delete only when no link,
   pointer, title or state is left to move.
3. It deletes each overlaid video: first the object, then the row. It does not
   delete a row while a designer revision points at it.
4. It deletes the SRT files, the logo, the remux jobs, the subtitle upload
   sessions, the remux temp objects and the worker temp objects of the
   `subtitle` and `overlaid_video` kinds.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Apply is complete. |
| 2 | The command refused to start. It made no change. |
| 3 | Apply is complete, but blocked overlaid videos stay. |
| 1 | An error stopped apply. Run apply again. |

Apply is safe to run again. If apply stops, run the same command again. A
second apply on a clean database shows `"done":{}` in the `SUMMARY` line.

## Drop the schema

```sh
docker exec "$container" bun run scripts/no_overlay_data_move.ts drop-schema --confirm
```

This step:

- drops the `subtitle_remux_jobs` table,
- drops the `project_overlay_logos` table,
- drops the `source_processing.srt_text` column,
- replaces `files_type_check` and `upload_sessions_type_check` with checks
  that do not allow `subtitle`.

It refuses while a subtitle file row or a subtitle upload session remains. It is
safe to run again. The old audit log entries for logo changes stay.

## Validation

1. Run `dry-run` again. The `SUMMARY` line must show `"work_left":0`.
2. Check `/healthz`.
3. Open a project. Each card shows the no-overlay video and the same active
   designer video as before.
4. Keep the dry-run and apply logs with the backup reference.

## Rollback

There is no automatic rollback. Deleted objects cannot come back. To restore
database rows, restore the backup into an isolated database and copy back only
the rows that you need.

## Test

The isolated Compose test seeds all of its rows and objects, and it runs all
three modes:

```sh
remote-js/tests/integration/run_no_overlay_data_move_flow.sh
```

When the Docker Hub MinIO images are not available, add
`NO_OVERLAY_TEST_COMPOSE_OVERRIDE=docker-compose.isolated.chainguard-minio.yml`.
