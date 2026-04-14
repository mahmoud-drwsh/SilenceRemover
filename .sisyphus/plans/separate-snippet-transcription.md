# Work Plan: Separate Snippet and Transcription Phases

## Overview
Split the current combined Phase 1 (snippet + transcription) into two distinct phases:
- **Phase 1**: Snippet Extraction (create silence-removed audio)
- **Phase 2**: Transcription (send snippet to OpenRouter)

This shifts all subsequent phases down by 1, becoming 7 total phases.

---

## Changes Required

### 1. Add is_snippet_done() Helper
**File**: `src/core/paths.py`
- Add function to check if snippet file exists
- Similar to `is_title_done()` - just check file existence
- Update `__all__` export list

### 2. Create run_snippet_phase() Function  
**File**: `src/app/pipeline.py`
- Extract snippet creation logic from current `run_transcription_phase()`
- Check if already done using `is_snippet_done()`
- No preconditions (can always run)
- Label: "Snippet Extraction"

### 3. Refactor run_transcription_phase()
**File**: `src/app/pipeline.py`
- Remove snippet creation logic (now in Phase 1)
- Add precondition: snippet must exist (`is_snippet_done`)
- Update phase index from 1 to 2
- Label: "Transcription"

### 4. Update All Phase Indices
**File**: `src/app/pipeline.py`
Update `total_phases=7` and renumber in all phase functions:
- `run_title_phase()`: 2 → 3
- `run_audio_upload_phase()`: 3 → 4
- `run_output_phase()`: 4 → 5
- `run_pending_upload_phase()`: 5 → 6  
- `run_video_upload_phase()`: 6 → 7

### 5. Update Phases Tuple in run()
**File**: `src/app/pipeline.py` (lines 869-956)
- Insert new Phase 1: `run_snippet_phase`
- Renumber all existing phases (+1)
- Update `total_phases = 7` in the phases tuple

### 6. Update Progress Messages
All phase progress messages need renumbering (e.g., "[1/7]" instead of "[1/6]")

---

## New Phase Flow

```
Phase 1: SNIPPET EXTRACTION
├── Check: snippet file exists?
├── Work: create_silence_removed_snippet()
└── Output: temp/snippet/{base36}.ogg

Phase 2: TRANSCRIPTION  
├── Check: transcript file with content exists?
├── Precondition: snippet must exist (Phase 1 done)
├── Work: transcribe_and_save() on snippet
└── Output: temp/transcript/{base36}.txt

Phase 3: TITLE GENERATION
├── Check: title file exists?
├── Precondition: transcript must exist (Phase 2 done)
├── Work: generate_title_from_transcript()
└── Output: temp/title/{base36}.txt

Phase 4: AUDIO UPLOAD (Media Manager)
├── Check: already uploaded?
├── Precondition: title exists
└── Upload snippet with tag "todo"

Phase 5: FINAL OUTPUT
├── Check: output video exists?
├── Precondition: approved on Media Manager
├── Work: trim_single_video() + overlays
└── Output: output/{base36}-{title}.mp4

Phase 6: STAGE TO PENDING
├── Check: already staged?
└── Work: prepare for publish

Phase 7: PUBLISH VIDEO
├── Check: already published?
└── Upload final video with tags
```

---

## Verification

After changes, pipeline should:
1. Successfully skip Phase 1 if snippet already exists
2. Successfully skip Phase 2 if transcript already exists  
3. Phase 2 should fail gracefully if Phase 1 not complete
4. All progress indicators show "X/7" instead of "X/6"
5. Final summary shows 7 phases complete
