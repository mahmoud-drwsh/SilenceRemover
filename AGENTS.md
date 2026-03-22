# Session change summaries for AI agents

After code or config changes, agents append short notes here. When this file grows past ~50 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Condensed changelog

- **Config & layout**: `.env` holds secrets (e.g. `OPENROUTER_API_KEY`); shared defaults live in `src/core/constants.py`. Packages: `src/core`, `src/media`, `src/llm`, `src/ffmpeg`, `src/startup`; orchestration in `src/app/pipeline.py`. Legacy top-level shim modules were removed.
- **FFmpeg layer**: Central builders, runners (including progress parsing), probing, silencedetect helpers, filter-graph utilities, and transcode command assembly. Scripted graphs use `-/filter_complex`; legacy `-filter_complex_script` fallback was dropped (FFmpeg 8+ assumed).
- **Encoding**: `src/ffmpeg/encoding_resolver.py` picks a runnable hardware HEVC profile (e.g. QSV, VideoToolbox) via probes/smoke tests; startup fails fast if none work; the resolved profile is passed into trim to avoid resolving again.
- **Silence & trim**: `TrimPlan` / `build_trim_plan` unify target vs non-target policies. `prepare_silence_intervals_with_edges` shares edge normalization across snippet, target, and non-target paths. Edge re-scan uses a relaxed threshold and a short keep buffer at file ends. Constants are grouped as `TARGET_*`, `NON_TARGET_*`, and `SNIPPET_*`. CLI requires positive `--target-length` and `--min-duration`; target mode supports threshold overrides and truncation when a target duration cannot be met.
- **Transcription snippet**: Phase 1 uses `create_silence_removed_snippet` with fixed snippet constants (ignores `--noise-threshold` / `--min-duration`); max length `SNIPPET_MAX_DURATION_SEC` (180s). Snippet path reuses the same edge policy as final trim.
- **Transcription audio**: Extraction pipeline favors OGG for the audio sent to the transcription model.
- **LLM client**: OpenRouter requests default to capping input/context and output size (10k tokens each), with compatibility handling if the API rejects some fields.
- **Default models**: Transcription and title flows default to `google/gemini-3.1-flash-lite-preview` on OpenRouter unless callers override.
- **Title generation**: Prompts require verbatim, beginning-only title spans from the full transcript. One model call emits a small JSON array of candidates; one call returns per-candidate `verbatim_score` and `correctness_score`; the highest combined score wins with deterministic tie-breaks. There is **no** separate honorific add/check LLM step after selection.
- **Documentation**: `README.md` and `ALGO.md` track architecture, CLI defaults, edge and snippet behavior, encoding, and title rules.

## Latest session edits

- `AGENTS.md`: Replaced the long per-file bullet history with a compact thematic changelog and clarified re-condensing when the file grows past ~50 lines.
- `src/core/cli.py`: Added `--llm-only` for transcription/title-only runs with console output and incremental `titles.txt` logging.
- `src/startup/bootstrap.py`: Added `llm_only` to `StartupContext`, optional `encoder`, and skipped hardware encoder resolution when `--llm-only` is set.
- `src/app/pipeline.py`: Branched `run()` for LLM-only mode (two phases, session header + per-title appends to `temp/titles.txt`, console dump, summary); parameterized phase step labels with `total_phases`; refactored `run_title_phase` for manifest appends on generate and skip.
- `README.md`: Documented `--llm-only`, `titles.txt` append behavior, and Phase 3 skip.
- `pwsh/Start-VerticalLlmDryRun.ps1`: Added helper to run `--llm-only` against the vertical raw video folder (same layout as `Start-VerticalVideoProcessing.ps1`).
- `src/app/pipeline.py`: Passed `title_path` into Phase 3 so the generated title file can be burned into the final video.
- `src/media/trim.py`: Added optional `title_path` handling to force FFmpeg encoding (no copy-input) and to select the title overlay filter graph.
- `src/ffmpeg/filter_graph.py`: Added a concat+burn-in filter graph that draws a full-width 50%-alpha black banner from `y=h/5` to `y=2*h/5` and centers the title text from a file.
- `src/ffmpeg/transcode.py`: Updated the minimal “all-audio-silence” fallback to optionally burn the title via `-vf drawbox+drawtext`.
- `src/core/constants.py`: Added title overlay/font constants and default font name for new PNG overlay pipeline.
- `src/core/paths.py`: Added helpers and temp directories for font cache and generated title overlay PNG storage.
- `src/core/cli.py`: Added `--title-font` option for Google Font configuration.
- `src/startup/bootstrap.py`: Threaded `title_font` through `StartupContext` using default constant.
- `src/app/pipeline.py`: Passed `title_font` into phase 3 output rendering path.
- `src/ffmpeg/probing.py`: Added exact video width/height probing helper for overlay rendering.
- `src/ffmpeg/filter_graph.py`: Replaced drawtext-based title graph with PNG overlay concat overlay variant.
- `src/ffmpeg/transcode.py`: Added PNG overlay support to minimal and final trim command builders.
- `src/media/title_overlay.py`: New module to download/cache Google Fonts and render exact-position RGBA title overlay PNGs.
- `src/media/trim.py`: Integrated title overlay generation, overlay command wiring, and font selection into final/minimal video render.
- `src/ffmpeg/__init__.py`: Exported title-overlay graph and video-dimension probe updates.
- `pyproject.toml`: Added Pillow dependency for PIL-based overlay rendering.
- `src/media/title_overlay.py`: Font download via Google Fonts CSS2 + direct TTF; Arabic overlay uses `arabic-reshaper` + `python-bidi`; removed temporary NDJSON debug logging.
- `pyproject.toml`: Added `arabic-reshaper` and `python-bidi` for Arabic title overlays.
- `src/ffmpeg/probing.py`: Added `probe_has_audio_stream` for ffprobe-based audio stream detection.
- `src/ffmpeg/detection.py`: Skip `silencedetect` when there is no audio stream; use `run(..., capture_output=True)` for silence parse (fixes missing `subprocess` import on audio files).
- `src/ffmpeg/filter_graph.py`: Added lavfi-backed concat graphs for video-only sources (`[1:a]` / `[2:a]` with title overlay).
- `src/ffmpeg/transcode.py`: Added `build_silent_audio_file_command` and `extra_silent_audio_lavfi` on final trim commands.
- `src/media/trim.py`: Silent snippet generation and video encode path for inputs without audio streams.
- `src/ffmpeg/__init__.py`: Exported new probe/filter/transcode helpers.
- `README.md`: Title font/overlay docs, Arabic/RTL shaping note, and video-only (no audio) pipeline behavior.
- `src/ffmpeg/filter_graph.py`: Updated PNG title overlay filters to `shortest=1` so looped image input cannot extend output video duration.
- `src/ffmpeg/transcode.py`: Updated minimal overlay fallback filter to `shortest=1` for consistent bounded duration behavior.
- `src/media/trim.py`: Removed leftover `[DEBUG]` progress-script instrumentation prints from silence-removed media execution.

- `src/core/constants.py`: Added title readability threshold constants for minimum readable font sizing and two-line fallback control.
- `src/media/title_overlay.py`: Added two-line split candidate search and a threshold-based fallback path that reruns sizing when single-line text would become too small.

- `src/media/title_overlay.py`: Hardened font fitting by adding a no-fit sentinel path, enforcing min-readable threshold for two-line selection, and adding final width/height-safe fallback sizing before render.
- `src/media/title_overlay.py`: When single-line text is below readability threshold, fall back to unconstrained two-line sizing when no split reaches the floor so two-line layout still wins over one tiny line.
- `src/core/constants.py`: Raised default min readable title font px and banner fraction so overlay text targets larger type.
- `src/media/title_overlay.py`: Always compare best two-line max font size to single-line when there are multiple words; adopt two-line when gain meets `TITLE_TWO_LINE_MIN_GAIN_PX`; removed readability-threshold-only gate.
- `src/core/constants.py`: Added `TITLE_TWO_LINE_MIN_GAIN_PX` for two-line vs single-line switching.
- `src/media/title_overlay.py`: Fixed edge bleed by sizing/centering with `textbbox` ink width (not `textlength`), using `anchor="lt"` for consistent metrics, and stacking multi-line height as summed line bboxes plus gaps.
- `ALGO.md`: Documented the title overlay PNG pipeline (dimensions, shaping, binary-search fit, two-line splits, bbox-based draw, tunables).
- `README.md`: Corrected Phase 3 overlay description (banner-sized PNG, overlay position) and linked to ALGO.md for layout details.
- `src/core/constants.py`: Set title banner to start at 1/6 frame height and span 2/6 of height (sixths model).
- `src/media/trim.py`: Use `TITLE_BANNER_START_FRACTION` and `TITLE_BANNER_HEIGHT_FRACTION` for overlay size and y position.
- `ALGO.md`: Documented sixths-based banner geometry and constant names.
- `README.md`: Updated Phase 3 overlay band description to H/6 through H/2.
- `src/core/constants.py`: Banner height set to 1/6 frame; added `TITLE_OVERLAY_MAX_LINES` and `TITLE_OVERLAY_MAX_LAYOUT_COMBINATIONS` for multi-line layout search.
- `src/media/title_overlay.py`: Replaced two-line-only optimizer with `_best_multi_line_layout` (2–K lines, combination cap, variance/more-lines tie-break).
- `ALGO.md` / `README.md`: Documented 1/6 band [H/6,H/3] and multi-line enumeration behavior.
- `src/app/title_editor_server.py`: New FastAPI localhost title editor (`/`, `/status`, `/save`), `probe_existing_server` for duplicate detection, uvicorn in a background thread, Refresh + JSON save that clears `completed` only when title text changes.
- `src/app/pipeline.py`: Start title editor after bootstrap (or skip if `/status` matches), run phases, then block on server thread until Ctrl+C; `run()` returns `StartupContext`.
- `pyproject.toml` / `uv.lock`: Added `fastapi` and `uvicorn` dependencies.
- `src/core/constants.py`: Added `FINAL_VIDEO_SOURCE_METADATA_KEY` for overlay final-encode provenance (`Path.name` of source video).
- `src/ffmpeg/transcode.py`: Pass optional `source_metadata_filename` into overlay `build_final_trim_command` / `build_minimal_video_command` as `-metadata`.
- `src/media/trim.py`: Thread `input_file.name` into those builders when a title overlay is used.
- `src/ffmpeg/probing.py`: Added `read_format_tags`, `delete_final_videos_matching_source` (editor-only; scans output MP4s by tag).
- `src/startup/title_editor_layout.py`: New `TitleEditorLayout` + `build_title_editor_layout` (no API key).
- `src/startup/__init__.py`: Exported title editor layout helpers.
- `src/app/title_editor_server.py`: Uses `TitleEditorLayout`; on title change deletes matching tagged outputs then updates title + `completed`; removed in-process uvicorn thread helpers.
- `src/app/pipeline.py`: Removed embedded title editor server.
- `serve_titles.py`: Standalone entry that runs uvicorn for the title editor.
- `pwsh/Start-VerticalTitleEditor.ps1`: Launches `serve_titles.py` for the vertical raw folder.
- `src/ffmpeg/probing.py`: `read_format_tags` handles `stdout` as str when `run()` uses `text=True` (fixes title editor save / ffprobe JSON parse).
- `src/core/constants.py`: Source provenance uses standard MP4 `comment` metadata (value = original filename); legacy `SILENCE_REMOVER_SOURCE` still matched when deleting old outputs.
- `src/ffmpeg/probing.py`: `_tag_matches_source` uses Unicode NFC normalization and case-insensitive `comment` keys so editor deletes match ffprobe/metadata vs macOS filenames.
- `src/ffmpeg/probing.py` / `src/app/title_editor_server.py`: Removed debug-session NDJSON instrumentation.
- `src/app/title_editor_server.py`: Full-width table layout; capped video column with ellipsis; title column uses remaining width; title fields are `textarea` with wrap/overflow so long text does not scroll horizontally.
