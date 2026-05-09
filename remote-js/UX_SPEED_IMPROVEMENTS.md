# Remote JS UX and Speed Improvements

Small, narrowly scoped changes that should be felt by users through faster actions, less waiting, or smoother workflows.

## Priority Candidates

### Keep the current list visible during action refreshes

- **Effort**: 3/10
- **User-felt impact**: 8/10
- **Why it matters**: After an action, the UI should not wipe the list and show a full loading state unless the user changed views.
- **Small commit shape**: Let `loadFiles()` refresh in the background after actions while keeping the current cards visible.

### Stop fetching every video when removing one folder tag

- **Effort**: 2/10
- **User-felt impact**: 7/10
- **Why it matters**: Removing one folder tag should not require downloading the whole video list first.
- **Small commit shape**: Pass the current card tags into the remove action, or store them on the card as `data-tags`.

### Cache admin S3 storage totals briefly

- **Effort**: 3/10
- **User-felt impact**: 6/10
- **Why it matters**: The admin dashboard should not count every storage object on every load.
- **Small commit shape**: Add a short in-process TTL cache, with an explicit refresh option for exact recounts.

## Nice To Haves

### Persist folder-scoped downloaded state

- **Effort**: 1-2/10
- **User-felt impact**: 5-6/10
- **Why it matters**: Download state is intentionally folder-scoped because each folder is used by a separate person. The useful improvement is making that state survive browser restarts.
- **Small commit shape**: Keep the existing folder scope, but store the marker in `localStorage` instead of `sessionStorage`, keyed by project, media type, and folder/tag.

Example keys:

```text
downloaded:ihyaa:video:FB
downloaded:ihyaa:video:TT
downloaded:ihyaa:video:custom-folder
```

### Add audio upload lifecycle logs

- **Effort**: 2/10
- **User-felt impact**: 3/10
- **Why it matters**: Users do not feel this directly, but upload failures become much faster to diagnose.
- **Small commit shape**: Add audio-side logs matching the existing video upload lifecycle logs.

### Cache token hash reads briefly

- **Effort**: 4/10
- **User-felt impact**: 5/10
- **Why it matters**: Repeated authenticated requests should not need to reread the same token hash from the database every time.
- **Small commit shape**: Add a short in-process token-hash cache inside the auth module and invalidate it on token changes.
