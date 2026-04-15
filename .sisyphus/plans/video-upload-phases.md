# Redesign Video Upload Phases (7-8 → 7-8-9)

## TL;DR

> **Quick Summary**: Split current video upload phases 7-8 into 3 dedicated phases — Reconciliation (delete mismatched videos), Upload (upload fresh or from trash), Tag Promotion (promote approved audio's videos to FB+TT). Add `delete_file()` and `include_trash` to MediaManagerClient. Remove 3 dead functions. Update total_phases from 8 → 9 across codebase.
> 
> **Deliverables**:
> - 3 new phase functions in `pipeline.py`: `run_video_reconciliation_phase`, `run_video_upload_phase` (renamed/new), `run_video_tag_promotion_phase`
> - `delete_file()` method on `MediaManagerClient` (two-step: tag trash then DELETE)
> - `include_trash` parameter on `get_video_files()` and `get_audio_files()`
> - Cache rebuild logic between phases 7-8 and 8-9
> - Remove 3 dead functions (lines 565-638)
> - Updated `total_phases=9`, phase wiring, exports, docs, tests
> 
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 4 waves
> **Critical Path**: Task 1 → Task 3 → Task 6 → Task 7

---

## Context

### Original Request
Redesign the video upload phases. Break them into small dedicated phases: (1) check if local title and uploaded video title don't match → remove from server, (2) upload video when not on server (including re-upload from trash), (3) if audio approved → change video tags to FB+TT.

### Interview Summary
**Key Discussions**:
- Delete from server only (don't clear local completion marker)
- Trash videos should be re-uploadable (delete from trash first)
- Dead code (3 unused functions) should be removed
- No automated unit tests needed — agent-executed QA only
- Total pipeline goes from 8 → 9 phases

**Research Findings**:
- Backend DELETE requires file to be trashed first (two-step: tag as trash, then DELETE)
- `ServerDataCache` is frozen/immutable, built once at pipeline start → stale after Phase 7 deletes
- `get_video_files()` excludes trash by default → `is_video_trash()` always returns False (latent bug)
- Backend upload auto-overwrites on title mismatch (idempotent for re-uploads)
- 3 dead functions call undefined `_get_media_manager_client()` — would crash at runtime

### Metis Review
**Identified Gaps** (all addressed):
- Cache staleness after Phase 7 deletes → Rebuild cache between phases
- `get_video_files()` missing `include_trash` → Add parameter
- `delete_file()` client method needed for two-step DELETE → Implement internally
- Phase 7 reconciliation should handle all title mismatches, not just pending
- Error handling: Phase 7 DELETE failure should return `False` (fail video, allow re-run)
- Phase number references spread across 7+ files → Comprehensive update task

---

## Work Objectives

### Core Objective
Replace the current Phases 7-8 (pending upload + video publish) with 3 focused phases: Reconciliation, Upload, Tag Promotion.

### Concrete Deliverables
- `MediaManagerClient.delete_file()` method
- `MediaManagerClient.get_video_files(include_trash=...)` and `get_audio_files(include_trash=...)` parameters
- `ServerDataCache` rebuild function
- 3 new phase functions replacing `run_pending_upload_phase` and `run_video_upload_phase`
- Removed dead code (3 functions)
- Updated `total_phases=9` across all files
- Updated docstrings, package `__init__.py`, README, ALGO.md, AGENTS.md

### Definition of Done
- [ ] `python main.py --quick-test` runs 9-phase pipeline without errors
- [ ] `python -c "from src.app.pipeline import run; print('OK')"` imports successfully
- [ ] `python -c "from sr_media_manager import MediaManagerClient; print('OK')"` imports successfully
- [ ] All phase number references updated to 9 across codebase

### Must Have
- Two-step delete in client (tag trash → DELETE)
- Cache rebuild between phases 7→8 and 8→9
- `include_trash` parameter on both `get_video_files()` and `get_audio_files()`
- Phase 7: Title mismatch → delete from server
- Phase 8: Upload if not on server; re-upload from trash
- Phase 9: Promote tags to FB+TT when audio approved
- Dead code removal (3 functions + undefined refs)
- All `total_phases` references updated to 9

### Must NOT Have (Guardrails)
- NO backend changes (`remote/app.py`)
- NO changes to Phases 1-6
- NO `ServerDataCache` mutation — rebuild it, don't mutate
- NO automated unit tests (agent QA only)
- NO changes to audio upload (Phase 4)
- NO new dependencies

---

## Verification Strategy (MANDATORY)

### Test Decision
- **Infrastructure exists**: YES (pytest/tests directory)
- **Automated tests**: None requested — agent-executed QA only
- **Framework**: N/A

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: Add `delete_file()` and `include_trash` to MediaManagerClient [quick]
└── Task 2: Remove dead code from pipeline.py [quick]

Wave 2 (After Wave 1 - core implementation):
├── Task 3: Implement Phase 7 — run_video_reconciliation_phase [deep] (depends: 1)
├── Task 4: Implement Phase 8 — run_video_upload_phase (new) [deep] (depends: 1)
└── Task 5: Implement Phase 9 — run_video_tag_promotion_phase [deep] (depends: 1)

Wave 3 (After Wave 2 - pipeline wiring):
├── Task 6: Wire 9 phases in run(), rebuild cache, update ServerDataCache [deep] (depends: 2, 3, 4, 5)
└── Task 7: Update all phase number references across codebase [quick] (depends: 6)

Wave FINAL (After ALL tasks):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
```

### Dependency Matrix

- **1**: - → 3, 4, 5
- **2**: - → 6
- **3**: 1 → 6
- **4**: 1 → 6
- **5**: 1 → 6
- **6**: 2, 3, 4, 5 → 7
- **7**: 6 → F1-F4

### Agent Dispatch Summary

- **Wave 1**: 2 tasks — T1 → `quick`, T2 → `quick`
- **Wave 2**: 3 tasks — T3 → `deep`, T4 → `deep`, T5 → `deep`
- **Wave 3**: 2 tasks — T6 → `deep`, T7 → `quick`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Add `delete_file()` and `include_trash` to MediaManagerClient

  **What to do**:
  - Add `delete_file(file_id: str, file_type: str = 'video') -> bool` method to `MediaManagerClient` in `packages/sr_media_manager/api.py`:
    - First call `update_tags(file_id, ['trash'], file_type=file_type)` to tag as trash
    - Then call `self._client.delete(self._url(f'/api/files/{file_id}?type={file_type}'))` to permanently delete
    - Return `True` on success, raise `MediaManagerError` on failure
    - If the 404 error occurs on DELETE (file already gone), return `True` (idempotent)
    - If the 400 error occurs on DELETE ("Only trashed files can be deleted"), the trash-tag step should have handled it, so raise `MediaManagerError`
  - Add `include_trash: bool = False` parameter to `get_video_files()` method:
    - When `include_trash=True`, append `&include_trash=true` to the URL
    - This allows the cache builder and phase functions to see trashed videos
  - Add `include_trash: bool = False` parameter to `get_audio_files()` method (already has this parameter, verify it passes it through correctly)
  - Add `delete_file` and `get_video_files` updates to `packages/sr_media_manager/__init__.py` exports

  **Must NOT do**:
  - DO NOT modify the backend (`remote/app.py`)
  - DO NOT add new dependencies

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Single-file API additions, well-scoped changes
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 2)
  - **Blocks**: Tasks 3, 4, 5
  - **Blocked By**: None

  **References** (CRITICAL):

  **Pattern References**:
  - `packages/sr_media_manager/api.py:266-376` — Existing `upload_video()` method pattern for HTTP calls, progress tracking, error handling
  - `packages/sr_media_manager/api.py:378-393` — Existing `update_tags()` method pattern (we call this as step 1 of delete)
  - `packages/sr_media_manager/api.py:50-70` — Existing `get_audio_files()` method for `include_trash` pattern reference
  - `packages/sr_media_manager/api.py:71-87` — Existing `get_video_files()` method to add `include_trash` parameter
  - `remote/app.py:627-681` — Backend DELETE endpoint implementation (confirms trash-then-delete requirement, line 660)
  - `packages/sr_media_manager/__init__.py:1-37` — Current exports to add `delete_file` to

  **API/Type References**:
  - `MediaManagerClient._url()` — URL builder for API endpoints
  - `MediaManagerError` — Custom exception class

  **WHY Each Reference Matters**:
  - `update_tags()`: We call this first in `delete_file()` to tag as trash before DELETE — must match its signature exactly
  - `get_audio_files()`: Already has `include_trash` — copy the same URL construction pattern for `get_video_files()`
  - Backend DELETE endpoint at line 660: Confirms "Only trashed files can be deleted" constraint — our two-step must handle this

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: delete_file method exists and follows two-step pattern
    Tool: Bash (python)
    Preconditions: MediaManagerClient imported
    Steps:
      1. python -c "from sr_media_manager import MediaManagerClient; assert hasattr(MediaManagerClient, 'delete_file'), 'delete_file missing'"
      2. python -c "from sr_media_manager import MediaManagerClient; import inspect; sig = inspect.signature(MediaManagerClient.delete_file); params = list(sig.parameters.keys()); assert 'file_id' in params and 'file_type' in params, f'Wrong params: {params}'"
    Expected Result: Both asserts pass without error
    Failure Indicators: AssertionError or ImportError
    Evidence: .sisyphus/evidence/task-1-delete-file-exists.txt

  Scenario: get_video_files includes include_trash parameter
    Tool: Bash (python)
    Preconditions: MediaManagerClient imported
    Steps:
      1. python -c "from sr_media_manager import MediaManagerClient; import inspect; sig = inspect.signature(MediaManagerClient.get_video_files); assert 'include_trash' in sig.parameters, 'include_trash missing'"
    Expected Result: Assert passes
    Failure Indicators: AssertionError
    Evidence: .sisyphus/evidence/task-1-include-trash-param.txt
  ```

  **Commit**: YES (groups with task commit)
  - Message: `feat(media-manager): add delete_file() method and include_trash parameter`
  - Files: `packages/sr_media_manager/api.py`, `packages/sr_media_manager/__init__.py`

- [x] 2. Remove dead code from pipeline.py

  **What to do**:
  - Remove the following 3 dead functions from `src/app/pipeline.py` (lines 565-638):
    1. `run_video_cleanup_phase` — uses undefined `_get_media_manager_client()`
    2. Old `run_video_upload_phase` (the one with `total_phases=9` and `_get_media_manager_client()`)
    3. `run_video_publish_phase` — uses undefined `_get_media_manager_client()`
  - Remove from `src/app/__init__.py` any exports referencing these functions (check if they're exported)
  - Remove any references to undefined `_get_media_manager_client`, `get_output_path`, or `clear_completion` from these dead functions
  - Verify no other code references these 3 functions (grep for their names)

  **Must NOT do**:
  - DO NOT remove the active `run_pending_upload_phase` (line 641) or `run_video_upload_phase` (line 727) — these are used in the pipeline
  - DO NOT modify any other phase functions

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple deletion of unused code
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: Task 6
  - **Blocked By**: None

  **References** (CRITICAL):

  **Pattern References**:
  - `src/app/pipeline.py:565-638` — The 3 dead functions to remove: `run_video_cleanup_phase`, `run_video_upload_phase` (old version), `run_video_publish_phase`
  - `src/app/__init__.py:1-25` — Current exports list to check for dead function references

  **WHY Each Reference Matters**:
  - Pipeline lines 565-638: Exact location of dead code — must remove all 3 functions completely
  - `__init__.py`: Check if any of the 3 dead functions are exported and remove those exports

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Dead functions removed, active functions intact
    Tool: Bash (python + grep)
    Preconditions: Pipeline file modified
    Steps:
      1. python -c "from src.app.pipeline import run_pending_upload_phase, run_video_upload_phase; print('active functions OK')"
      2. grep -n "run_video_cleanup_phase\|_get_media_manager_client" src/app/pipeline.py
      3. grep -n "def run_video_cleanup_phase\|def run_video_publish_phase" src/app/pipeline.py
    Expected Result: Step 1 imports succeed. Steps 2-3 return no matches (dead code removed).
    Failure Indicators: ImportError on step 1, or grep finds matches in steps 2-3
    Evidence: .sisyphus/evidence/task-2-dead-code-removed.txt
  ```

  **Commit**: YES (groups with task commit)
  - Message: `refactor(pipeline): remove dead video phase functions`
  - Files: `src/app/pipeline.py`, `src/app/__init__.py`

- [x] 3. Implement Phase 7 — run_video_reconciliation_phase

  **What to do**:
  - Create `run_video_reconciliation_phase()` in `src/app/pipeline.py`
  - Signature: `(video_path, video_index, total_videos, server_cache, progress=None, *, total_phases=9) -> bool | None`
  - Logic:
    1. If `server_cache` is `None` → return `None` (skip, Media Manager not enabled)
    2. Get `basename = video_path.stem`, `file_id = basename`
    3. Read local title from `output/temp/title/{basename}.txt` — if missing or empty, skip (return `None`)
    4. Look up video on server via `server_cache.get_video(file_id)` — if not found, skip (return `None`, nothing to reconcile)
    5. Compare `server_title.strip()` with `local_title.strip()` — if they match, skip (return `None`, no reconciliation needed)
    6. If titles DON'T match: use `MediaManagerClient` to:
       a. Call `client.update_tags(file_id, ['trash'], file_type='video')` — tag as trash first
       b. Call `client.delete_file(file_id, file_type='video')` — then permanently delete
       c. Log the reconciliation: `print(f"[Reconciliation] Deleted server video {file_id}: title changed from '{server_title}' to '{local_title}'")`
    7. Return `True` on successful deletion, `False` on failure
  - Use `_run_phase_step()` pattern matching other phases
  - Set `failure_label="Phase 7"`, `label="Video Reconciliation"`, `phase_index=7`

  **Must NOT do**:
  - DO NOT clear the local completion marker (don't call `mark_completed` or delete completed files)
  - DO NOT modify any other phase functions
  - DO NOT create the `MediaManagerClient` outside `_perform()` (follow existing pattern)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding server state, cache, and two-step delete logic
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 4 and 5)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 6
  - **Blocked By**: Task 1 (needs `delete_file()` method)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/app/pipeline.py:591-638` — Old `run_video_upload_phase` and `run_video_publish_phase` as reference for client creation and server interaction patterns (BEFORE removal by Task 2)
  - `src/app/pipeline.py:400-473` — `run_audio_upload_phase` as pattern for phase function with `server_cache`, `MediaManagerClient()` creation in `_perform()`, and skip logic
  - `src/app/pipeline.py:727-816` — Current `run_video_upload_phase` as pattern for server state checks and `_run_phase_step()` usage

  **API/Type References**:
  - `src/app/pipeline.py:364-395` — `ServerDataCache` dataclass with `get_video()`, `is_video_trash()` methods
  - `packages/sr_media_manager/api.py:378-393` — `update_tags()` method signature: `(file_id, tags, file_type='audio')`
  - Task 1 deliverable: `delete_file(file_id, file_type='video')` method on `MediaManagerClient`

  **Test References**:
  - Follow existing `_run_phase_step()` pattern exactly

  **WHY Each Reference Matters**:
  - `run_audio_upload_phase`: Best reference for how to create `MediaManagerClient` inside `_perform()`, read from cache, and handle skip conditions
  - `ServerDataCache`: Shows the exact API for checking video state from cache
  - `update_tags()` / `delete_file()`: The two-step delete must call these in sequence — `update_tags` first, then `delete_file`

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: run_video_reconciliation_phase function exists with correct signature
    Tool: Bash (python)
    Preconditions: Pipeline module importable
    Steps:
      1. python -c "from src.app.pipeline import run_video_reconciliation_phase; import inspect; sig = inspect.signature(run_video_reconciliation_phase); print(f'Params: {list(sig.parameters.keys())}')"
    Expected Result: Function imports, params include 'video_path', 'video_index', 'total_videos', 'server_cache', 'total_phases'
    Failure Indicators: ImportError or missing params
    Evidence: .sisyphus/evidence/task-3-reconciliation-exists.txt

  Scenario: Title mismatch triggers delete (two-step), title match skips, no video skips
    Tool: Bash (python)
    Preconditions: Pipeline module importable
    Steps:
      1. python -c "import ast, inspect; src = inspect.getsource(__import__('src.app.pipeline', fromlist=['pipeline']).run_video_reconciliation_phase); tree = ast.parse(src); calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]; print(f'Method calls: {calls}')"
    Expected Result: Method calls include 'update_tags' and 'delete_file' AND 'get_video' (from cache)
    Failure Indicators: Missing 'update_tags' or 'delete_file' in method calls
    Evidence: .sisyphus/evidence/task-3-two-step-delete.txt
  ```

  **Commit**: YES
  - Message: `feat(pipeline): add Phase 7 video reconciliation phase`
  - Files: `src/app/pipeline.py`

- [x] 4. Implement Phase 8 — run_video_upload_phase (new)

  **What to do**:
  - Create a NEW `run_video_upload_phase()` in `src/app/pipeline.py` (this replaces the old one which was removed in Task 2 AND the old `run_pending_upload_phase`)
  - Signature: `(video_path, output_dir, temp_dir, video_index, total_videos, server_cache, progress=None, *, total_phases=9) -> bool | None`
  - Logic:
    1. If `server_cache` is `None` → return `None` (skip, Media Manager not enabled)
    2. Get `basename = video_path.stem`, `file_id = basename`
    3. Check local completion: `if not is_completed(temp_dir, basename)` → return `None`
    4. Read local title from `get_title_path` — if missing or empty, skip
    5. Get `output_basename` from `get_completed_output_filename()` — fallback to `sanitize_filename(title_text)`
    6. Get `output_path = output_dir / f"{output_basename}.mp4"`
    7. Check server state via `server_cache.get_video(file_id)`:
       a. If video exists with matching title AND tags include `FB` or `TT` → skip (already published, return `None`)
       b. If video exists with matching title AND tags include `pending` (but not FB/TT) → skip (will be promoted in Phase 9, return `None`)
       c. If video exists with matching title and other tags → skip (return `None`)
    8. Check if video is in trash: `if server_cache.is_video_trash(file_id)` → delete from trash first:
       a. `client.delete_file(file_id, file_type='video')`
       b. Fall through to upload below
    9. If video exists with DIFFERENT title → Phase 7 should have already handled this, but as a safety net: skip (return `None`), rely on Phase 7 reconciliation
    10. If video not on server at all → upload:
       a. `client.upload_video(file_id, local_title, output_path, tags=['pending'], progress_callback=...)`
       b. Notify with `notify_video_uploaded(video_index, total_videos, input_name=video_path.name, title=local_title)` (add this to telegram notify package)
    11. Return `True` on success, `False` on failure
  - Use `_run_phase_step()` pattern
  - Set `failure_label="Phase 8"`, `label="Video Upload"`, `phase_index=8`

  **Must NOT do**:
  - DO NOT set tags to `['FB', 'TT']` in upload — Phase 9 handles tag promotion
  - DO NOT check `is_audio_ready()` — that's Phase 9's responsibility
  - DO NOT clear local completion markers

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex state machine logic with multiple skip conditions and server interaction
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 3 and 5)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 6
  - **Blocked By**: Task 1 (needs `delete_file()` method)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/app/pipeline.py:641-724` — Current `run_pending_upload_phase` as primary reference for upload-with-progress pattern, `MediaManagerClient` creation, and `_run_phase_step()` usage
  - `src/app/pipeline.py:727-816` — Current `run_video_upload_phase` as reference for server state checks and FB/TT tag detection
  - `src/app/pipeline.py:400-473` — `run_audio_upload_phase` for `server_cache` pattern

  **API/Type References**:
  - `packages/sr_media_manager/api.py:266-376` — `upload_video()` method signature and progress callback pattern
  - `packages/sr_media_manager/api.py:156-198` — `check_video_exists()` for pre-flight check pattern
  - `src/core/paths.py` — `get_completed_output_filename()`, `is_completed()`, `get_title_path()` for path resolution
  - Task 1 deliverable: `delete_file()` method on `MediaManagerClient`

  **WHY Each Reference Matters**:
  - `run_pending_upload_phase`: Closest pattern for upload logic with progress tracking and `server_cache` usage
  - `run_video_upload_phase`: Has the server state check patterns (title match, tag detection) to replicate
  - `upload_video()`: Need to know exact signature for the upload call with `tags=['pending']`

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: run_video_upload_phase function exists and uploads with pending tags
    Tool: Bash (python)
    Preconditions: Pipeline module importable
    Steps:
      1. python -c "from src.app.pipeline import run_video_upload_phase; print('OK')"
    Expected Result: Function imports successfully
    Failure Indicators: ImportError
    Evidence: .sisyphus/evidence/task-4-upload-phase-exists.txt

  Scenario: Upload uses pending tags (not FB+TT)
    Tool: Bash (python)
    Preconditions: Pipeline source accessible
    Steps:
      1. python -c "import inspect; src = inspect.getsource(__import__('src.app.pipeline', fromlist=['pipeline']).run_video_upload_phase); assert \"tags=['pending']\" in src or '\"pending\"' in src, 'Must upload with pending tags'; print('pending tags found')"
    Expected Result: Assert passes — upload uses `tags=['pending']`, not `tags=['FB', 'TT']`
    Failure Indicators: AssertionError — FB+TT tags used instead of pending
    Evidence: .sisyphus/evidence/task-4-pending-tags.txt
  ```

  **Commit**: YES
  - Message: `feat(pipeline): add Phase 8 video upload phase`
  - Files: `src/app/pipeline.py`

- [x] 5. Implement Phase 9 — run_video_tag_promotion_phase

  **What to do**:
  - Create `run_video_tag_promotion_phase()` in `src/app/pipeline.py`
  - Signature: `(video_path, output_dir, temp_dir, video_index, total_videos, server_cache, progress=None, *, total_phases=9) -> bool | None`
  - Logic:
    1. If `server_cache` is `None` → return `None` (skip, Media Manager not enabled)
    2. Get `basename = video_path.stem`, `file_id = basename`
    3. Check if audio is ready: `if not server_cache.is_audio_ready(file_id)` → return `None` (skip, audio not yet approved)
    4. Check server state: `video = server_cache.get_video(file_id)`
       a. If video not on server → return `None` (skip, nothing to promote — Phase 8 should handle upload)
       b. If video has `FB` or `TT` in tags → return `None` (already promoted)
    5. If video is on server and audio is ready → promote tags:
       a. `client = MediaManagerClient(os.getenv('MEDIA_MANAGER_URL'))`
       b. `client.update_tags(file_id, ['FB', 'TT'], file_type='video')`
       c. Close client
    6. Return `True` on success (tags promoted), `False` on failure
  - Use `_run_phase_step()` pattern
  - Set `failure_label="Phase 9"`, `label="Tag Promotion"`, `phase_index=9`

  **Must NOT do**:
  - DO NOT upload video — Phase 8 handles upload
  - DO NOT check `is_video_trash()` — if video is trash, Phase 7/8 handle it
  - DO NOT promote if audio is not ready — this is the key gate

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Requires understanding server state and audio readiness checks
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Tasks 3 and 4)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 6
  - **Blocked By**: Task 1 (needs `MediaManagerClient` with `update_tags`)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/app/pipeline.py:618-638` — Old `run_video_publish_phase` as reference for tag update pattern (BEFORE removal by Task 2)
  - `src/app/pipeline.py:727-816` — Current `run_video_upload_phase` as reference for `is_audio_ready()` check

  **API/Type References**:
  - `packages/sr_media_manager/api.py:378-393` — `update_tags()` method signature
  - `src/app/pipeline.py:364-395` — `ServerDataCache.is_audio_ready()` and `get_video()` methods

  **WHY Each Reference Matters**:
  - Old `run_video_publish_phase`: Contains the exact `client.update_tags()` call pattern we need
  - Current `run_video_upload_phase`: Has the FB/TT tag detection pattern and `is_audio_ready()` check pattern

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: run_video_tag_promotion_phase function exists with correct gates
    Tool: Bash (python)
    Preconditions: Pipeline module importable
    Steps:
      1. python -c "from src.app.pipeline import run_video_tag_promotion_phase; print('OK')"
    Expected Result: Function imports successfully
    Failure Indicators: ImportError
    Evidence: .sisyphus/evidence/task-5-promotion-exists.txt

  Scenario: Tag promotion uses update_tags with FB+TT
    Tool: Bash (python)
    Preconditions: Pipeline source accessible
    Steps:
      1. python -c "import inspect; src = inspect.getsource(__import__('src.app.pipeline', fromlist=['pipeline']).run_video_tag_promotion_phase); assert \"['FB', 'TT']\" in src, 'Must use FB+TT tags'; assert 'update_tags' in src, 'Must call update_tags'; print('OK')"
    Expected Result: Assert passes — function calls `update_tags` with `['FB', 'TT']`
    Failure Indicators: AssertionError
    Evidence: .sisyphus/evidence/task-5-fb-tt-tags.txt
  ```

  **Commit**: YES
  - Message: `feat(pipeline): add Phase 9 tag promotion phase`
  - Files: `src/app/pipeline.py`

- [x] 6. Wire 9 phases in run(), rebuild cache between phases 7→8 and 8→9, update ServerDataCache

  **What to do**:
  - In `src/app/pipeline.py`, update the `run()` function:
    1. Change `total_phases = 8` to `total_phases = 9`
    2. Replace the Phase 7 `_PipelinePhase` entry with `run_video_reconciliation_phase`
    3. Replace the Phase 8 `_PipelinePhase` entry with the new `run_video_upload_phase`
    4. Add Phase 9 `_PipelinePhase` entry with `run_video_tag_promotion_phase`
    5. Add cache rebuild logic between phases 7→8 and 8→9:
       - After `_run_phase()` for Phase 7, rebuild `server_cache` if `media_manager_enabled`:
         ```python
         if media_manager_enabled:
             server_cache = _rebuild_server_cache()  # New helper
         ```
       - After `_run_phase()` for Phase 8, rebuild again:
         ```python
         if media_manager_enabled:
             server_cache = _rebuild_server_cache()
         ```
    6. Extract the existing cache-building code (lines 846-889) into a `_rebuild_server_cache()` helper function that returns a new `ServerDataCache`. This function should also pass `include_trash=True` to `get_video_files()` so trash state is visible.
    7. Update all phase lambda functions to pass `server_cache=server_cache` (refreshed between phases)
  - Update `src/app/__init__.py`:
    1. Remove `run_pending_upload_phase` export
    2. Remove old `run_video_upload_phase` export (the one we replaced)
    3. Add `run_video_reconciliation_phase`, `run_video_upload_phase` (new), `run_video_tag_promotion_phase`
  - Add `notify_video_uploaded` to `packages/sr_telegram_notify/api.py` (Phase 8 completion notification, mirroring `notify_audio_uploaded` pattern) — ONLY if it doesn't exist yet; check first
  - Update `packages/sr_telegram_notify/__init__.py` exports if adding `notify_video_uploaded`

  **Must NOT do**:
  - DO NOT change the `_run_phase_step` pattern
  - DO NOT make `ServerDataCache` mutable — rebuild it fresh
  - DO NOT modify Phases 1-6 in any way

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex wiring with cache rebuilds, phase ordering, and multiple file changes
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential, depends on Tasks 2-5)
  - **Blocks**: Task 7
  - **Blocked By**: Tasks 2, 3, 4, 5

  **References** (CRITICAL):

  **Pattern References**:
  - `src/app/pipeline.py:819-1033` — Current `run()` function with phase wiring, cache building, and phase loop
  - `src/app/pipeline.py:844-889` — Current cache building code to extract into `_rebuild_server_cache()`
  - `src/app/pipeline.py:898-1027` — Current `_PipelinePhase` tuple with 8 phases to replace with 9

  **API/Type References**:
  - `src/app/pipeline.py:364-395` — `ServerDataCache` dataclass (frozen, so we rebuild rather than mutate)
  - `packages/sr_media_manager/api.py:71-87` — `get_video_files()` method to add `include_trash=True` to
  - `packages/sr_telegram_notify/api.py:110-127` — `notify_audio_uploaded` pattern for new `notify_video_uploaded`
  - `src/app/__init__.py:1-25` — Current exports to update

  **WHY Each Reference Matters**:
  - `run()`: The entire wiring needs to change from 8 to 9 phases, with cache rebuilds between 7→8 and 8→9
  - Cache building code: Must extract and modify to include trash videos (`include_trash=True`)
  - `_PipelinePhase` tuple: Must match the exact lambda pattern for new phase functions
  - `ServerDataCache`: Frozen dataclass — need to understand why we rebuild instead of mutate

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Pipeline has 9 phases wired correctly
    Tool: Bash (python)
    Preconditions: Pipeline module importable
    Steps:
      1. python -c "import inspect; from src.app.pipeline import run; src = inspect.getsource(run); assert 'total_phases = 9' in src or 'total_phases=9' in src, 'Must be 9 phases'; print('9 phases confirmed')"
    Expected Result: Assert passes, pipeline configured for 9 phases
    Failure Indicators: AssertionError — still says 8
    Evidence: .sisyphus/evidence/task-6-nine-phases.txt

  Scenario: Cache rebuild between phases 7-8 and 8-9
    Tool: Bash (python)
    Preconditions: Pipeline source accessible
    Steps:
      1. python -c "import inspect; from src.app.pipeline import run; src = inspect.getsource(run); assert '_rebuild_server_cache' in src, 'Must have cache rebuild helper'; assert src.count('_rebuild_server_cache()') >= 2, 'Must rebuild at least twice (after phase 7 and 8)'; print('cache rebuild OK')"
    Expected Result: Assert passes — cache rebuilds exist after Phase 7 and Phase 8
    Failure Indicators: AssertionError
    Evidence: .sisyphus/evidence/task-6-cache-rebuild.txt

  Scenario: Exports updated correctly
    Tool: Bash (python)
    Preconditions: Module importable
    Steps:
      1. python -c "from src.app import run_video_reconciliation_phase, run_video_upload_phase, run_video_tag_promotion_phase; print('new exports OK')"
    Expected Result: All 3 new phase functions importable
    Failure Indicators: ImportError
    Evidence: .sisyphus/evidence/task-6-exports.txt
  ```

  **Commit**: YES
  - Message: `refactor(pipeline): wire 9 phases, rebuild cache between phases 7-9`
  - Files: `src/app/pipeline.py`, `src/app/__init__.py`, `packages/sr_telegram_notify/api.py` (if adding notify_video_uploaded), `packages/sr_telegram_notify/__init__.py` (if adding export)

- [x] 7. Update all phase number references across codebase

  **What to do**:
  - Search and replace all phase number references from 8 → 9 across these files:
    1. `src/app/pipeline.py` — Docstring "Eight-phase" → "Nine-phase", all `total_phases=8` defaults → `total_phases=9` in existing phase functions that still have it
    2. `packages/sr_media_manager/__init__.py` — "8-phase workflow" → "9-phase workflow", "Phase 8" → "Phase 9" for video upload description, "Phase 4 and Phase 8" → "Phase 4, Phase 8, and Phase 9"
    3. `packages/sr_media_manager/upload.py` — Docstring "Phase 3 and Phase 5" → verify correctness for current phases
    4. `packages/sr_telegram_notify/api.py` — Update "Phase 6" and "Phase 8" references:
       - `notify_final_output_ready`: Update phase_index references for new numbering (Phase 6 → Phase 6 stays the same for encoding; "Phase 8" → "Phase 9" for video publish notification)
       - Add `notify_video_uploaded` for Phase 8 if added in Task 6
    5. `README.md` — "8-phase workflow" → "9-phase workflow", add Phase 7/8/9 descriptions, update Phase 7 from "Stage video to pending" to "Video Reconciliation", Phase 8 to "Upload Video", Phase 9 to "Promote Tags"
    6. `ALGO.md` — Update any phase references
    7. `AGENTS.md` — Update condensed changelog to mention the phase redesign
    8. `tests/test_pipeline_display.py` — Change `total_phases=8` → `total_phases=9` in all 5 occurrences
    9. `remote/README.md` — Update "SilenceRemover Integration" section if it references specific phase numbers
    10. `remote/SERVICE_PLAN.md` — Update any phase references
  - Verify no remaining `8-phase` or `total_phases=8` or `"Phase 8"` (in context of video upload) references

  **Must NOT do**:
  - DO NOT change Phases 1-6 descriptions or numbering
  - DO NOT modify backend code (`remote/app.py`)
  - DO NOT add or remove functionality — this is a documentation/reference update only

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Search-and-replace across known files, no logic changes
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after Task 6)
  - **Blocks**: F1-F4
  - **Blocked By**: Task 6

  **References** (CRITICAL):

  **Pattern References**:
  - `src/app/pipeline.py:1` — Module docstring "Eight-phase"
  - `packages/sr_media_manager/__init__.py:1-6` — "8-phase workflow" docstring
  - `packages/sr_telegram_notify/api.py:110-127` — Phase number comments
  - `README.md:71-79` — Phase listing and "8-phase" references
  - `tests/test_pipeline_display.py:26-62` — `total_phases=8` occurrences

  **WHY Each Reference Matters**:
  - Every file listed has explicit phase number strings that must change from 8 to 9

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: No remaining 8-phase references
    Tool: Bash (grep)
    Preconditions: All files updated
    Steps:
      1. grep -rn "8-phase\|eight phase\|Eight.phase\|total_phases=8" src/ packages/ README.md ALGO.md tests/ --include="*.py" --include="*.md"
    Expected Result: Zero matches (all updated to 9-phase)
    Failure Indicators: Any matches found
    Evidence: .sisyphus/evidence/task-7-no-8-phase.txt

  Scenario: Pipeline imports and runs cleanly
    Tool: Bash (python)
    Preconditions: All changes applied
    Steps:
      1. python -c "from src.app.pipeline import run; print('import OK')"
    Expected Result: Module imports without error
    Failure Indicators: ImportError
    Evidence: .sisyphus/evidence/task-7-import.txt
  ```

  **Commit**: YES
  - Message: `docs: update all phase number references from 8 to 9`
  - Files: Multiple (README.md, ALGO.md, AGENTS.md, src/app/pipeline.py, packages/sr_media_manager/__init__.py, packages/sr_telegram_notify/api.py, tests/test_pipeline_display.py, etc.)

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [x] F1. **Plan Compliance Audit** — `oracle` (APPROVE)
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high` (REJECT - pre-existing Win32 ctypes bug, not from this plan)
  Run `python -c "from src.app.pipeline import run"` + `python -c "from sr_media_manager import MediaManagerClient"`. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Build [PASS/FAIL] | Lint [PASS/FAIL] | Imports [N/N pass] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high` (PASS)
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (phases 7→8→9 chain with server cache refresh). Test edge cases: title mismatch, trash state, already-published video. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep` (APPROVE)
  For each task: read "What to do", read actual diff (git diff). Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **1**: `feat(media-manager): add delete_file() method and include_trash parameter` - packages/sr_media_manager/api.py, packages/sr_media_manager/__init__.py
- **2**: `refactor(pipeline): remove dead video phase functions` - src/app/pipeline.py
- **3**: `feat(pipeline): add Phase 7 video reconciliation phase` - src/app/pipeline.py
- **4**: `feat(pipeline): add Phase 8 video upload phase` - src/app/pipeline.py
- **5**: `feat(pipeline): add Phase 9 tag promotion phase` - src/app/pipeline.py
- **6**: `refactor(pipeline): wire 9 phases, rebuild cache between phases 7-9` - src/app/pipeline.py
- **7**: `docs: update all phase number references from 8 to 9` - README.md, ALGO.md, AGENTS.md, others

---

## Success Criteria

### Verification Commands
```bash
python -c "from src.app.pipeline import run; print('OK')"  # Expected: OK
python -c "from sr_media_manager import MediaManagerClient; print('OK')"  # Expected: OK
python -c "from src.app.pipeline import run_video_reconciliation_phase, run_video_upload_phase, run_video_tag_promotion_phase; print('OK')"  # Expected: OK
grep -rn "total_phases=8" src/ packages/  # Expected: no matches (all should be 9)
grep -rn "8-phase" README.md ALGO.md packages/  # Expected: no matches (all should be 9-phase)
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] Pipeline runs 9 phases without errors
- [ ] Dead code fully removed
- [ ] Cache rebuilds between phases 7→8 and 8→9