# Draft: Redesign Video Upload Phases

## Requirements (confirmed)
- Split current Phases 7-8 (video upload) into 3 dedicated phases
- Phase A (Reconciliation): If local title ≠ server video title, delete video from server completely
- Phase B (Upload): Upload video when it's not on server and not in any folder (including trash)
- Phase C (Tag Promotion): If audio is approved (ready), change video tags to FB+TT
- Total pipeline goes from 8 → 9 phases

## Technical Decisions
- Delete video from server = two-step (tag trash, then DELETE) per backend API rule
- Phase A: title mismatch → delete from server only (don't clear local completion marker)
- Phase B: trash videos → delete from trash then re-upload fresh
- Dead code: remove 3 unused functions (cleanup, old upload, old publish)
- `MediaManagerClient` needs new `delete_file()` method for two-step delete
- `ServerDataCache` needs refresh method for inter-phase cache staleness
- Total pipeline: 8 → 9 phases

## Research Findings
- Current Phase 7 (`run_pending_upload_phase`) uploads with tags=["pending"]
- Current Phase 8 (`run_video_upload_phase`) either updates existing pending video tags to FB+TT or uploads fresh with FB+TT
- Dead code exists: `run_video_cleanup_phase` (title mismatch → delete), old `run_video_upload_phase` (total_phases=9), `run_video_publish_phase` (tag update) — these use undefined `_get_media_manager_client()` and are never called
- `ServerDataCache` is built once at pipeline start and reused across phases
- `MediaManagerClient` has methods: `upload_video`, `update_tags`, `check_video_exists`, `get_video_files`, `delete_video`
- `delete_video` method exists in the client (via PUT /api/files/{id} or similar) — need to verify
- `ServerDataCache` tracks: `audio_files`, `video_files`, `audio_trash_ids`, `video_trash_ids`, `ready_audio_ids`

## Open Questions
- ~~Dead code removal~~ → YES, remove
- ~~Re-encode after delete~~ → NO, only delete from server
- ~~Trash video handling~~ → Re-upload from trash
- Test strategy?

## Scope Boundaries
- INCLUDE: Pipeline phase functions, ServerDataCache, phase wiring in `run()`
- EXCLUDE: Media Manager backend changes, audio upload phases, snippet/transcription/title phases