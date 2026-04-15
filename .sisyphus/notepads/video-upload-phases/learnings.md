
## [TASK 2] Dead code removal
- `src/app/pipeline.py`: Removed 3 dead functions (lines 565-638): run_video_cleanup_phase, old run_video_upload_phase, run_video_publish_phase — all used undefined _get_media_manager_client()
- Active functions preserved: run_pending_upload_phase (line 565), run_video_upload_phase (line 651 new version)
- `__init__.py` already only exports active functions — no change needed
- Verification: grep confirms 0 matches for all 3 dead names

## [TASK 1] delete_file + include_trash
- `packages/sr_media_manager/api.py`: Added `delete_file()` method (two-step: tag trash → DELETE), added `include_trash` param to `get_video_files()`
- `packages/sr_media_manager/__init__.py`: No change needed — `delete_file` is a `MediaManagerClient` method, already exported via `MediaManagerClient`

## [TASK 3] Phase 7 run_video_reconciliation_phase
- Added to `src/app/pipeline.py` before run_pending_upload_phase
- Uses two-step delete: `update_tags(['trash'])` + `delete_file()`
- Reads local title from `temp_dir/TITLE_DIR/{basename}.txt`
- Skips if titles match (server_title == local_title)
- Uses `_run_phase_step()` pattern like other phases
- Updated `src/app/__init__.py` to export `run_video_reconciliation_phase`
- Renumbered phases 7→8 (Stage to Pending) and 8→9 (Publish Video)
- `total_phases` updated from 8 to 9

## [TASK 5] Phase 9 run_video_tag_promotion_phase
- Added after run_video_upload_phase (Phase 8)
- Promotes pending videos to FB+TT when audio is ready
- Uses update_tags(['FB', 'TT'], file_type='video')

## [TASK 4] Phase 8 run_video_upload_phase (new)
- Added NEW run_video_upload_phase before the existing one (now Phase 9)
- Uploads with tags=['pending'], handles trash re-upload
- Checks server state: skips if FB/TT or pending exists, skips on title mismatch (Phase 7 handles)
- Old run_video_upload_phase became Phase 9 (FB+TT publish)

## [TASK 6] Cache rebuild + remove run_pending_upload_phase
- `src/app/pipeline.py`: Extracted cache-building into `_rebuild_server_cache()` helper
- `_rebuild_server_cache()` uses `include_trash=True` for both audio and video
- Replaced inline cache-building in `run()` with single `_rebuild_server_cache()` call
- Added cache rebuilds in phases loop after Phase 7 and Phase 8 (fresh server state for next phase)
- Removed `run_pending_upload_phase` (dead code, 83 lines)
- Updated `src/app/__init__.py` to remove `run_pending_upload_phase` from imports and `__all__`
- Verification: grep returns no matches for `run_pending_upload_phase` in .py files, 9 phases confirmed

## [TASK 7] Phase number reference updates (8→9)
- `src/app/pipeline.py`: Updated docstring "eight-phase" → "nine-phase"
- `src/core/cli.py`: Updated help text "8-phase workflow" → "9-phase workflow"
- `packages/sr_media_manager/__init__.py`: Updated docstring "8-phase" → "9-phase", updated phase descriptions (Phase 8: pending, Phase 9: FB+TT)
- `README.md`: Updated 8-phase → 9-phase workflow; updated phase list (7: reconciliation, 8: pending upload, 9: FB+TT promotion); "eight phases" → "nine phases"
- `tests/test_pipeline_display.py`: Updated all `total_phases=8` → `total_phases=9`
- `AGENTS.md`: Updated historical session notes (8→9) for accuracy
- Verification: grep for "8 phase|8-phase|eight.phase" and "total_phases = 8" all return no matches
