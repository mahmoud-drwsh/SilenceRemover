# Session change summaries for AI agents

Entries below are appended by the agent after making code or config changes.

## Condensed older entries (1-74)

**Debug cleanup & early config**: Removed DEBUG globals and CLI flags from main.py, trim.py, and silence_utils.py. Set default models to gemini-2.5-flash-lite, then gemini-3.1-flash-lite-preview for titles. Added honorific prompt template.

**Target-length mode evolution**: Added AUTO_* constants for adaptive sweeps (min-duration-first, then dB), then replaced with SIMPLE_DB/SIMPLE_MIN_DURATION fixed-threshold mode. Introduced _build_segments_from_silences() helper, find_optimal_padding(), and detect_silences_simple(). Documented algorithm in ALGO.md.

**Environment cleanup**: Reduced .env to only OPENROUTER_API_KEY. Updated config.py docstring and README.md to reflect secrets-only approach. Added CLI flags --noise-threshold and --min-duration.

**OpenRouter SDK migration**: Replaced requests with official openrouter dependency. Created src/openrouter_client.py with shared request/retry logic and app attribution (http_referer, x_title). Added log_dir parameter for per-request logging. Switched transcribe.py and title.py to use SDK.

**Title generation**: Extracted honorific rules to ADD_HONORIFIC_PROMPT_TEMPLATE. Implemented two-step title flow (generate title, then add honorifics). Added _first_line helper and fallback on honorific step failure.

**Audio format**: Switched to OGG/Opus for smaller transcription payloads (libopus at 16kHz mono).

**Package refactoring**: Created src/transcription/openrouter.py + shim, src/titles/openrouter.py + shim, src/silence/detector.py + shim to preserve backward-compatible import paths. Changed logging to per-request timestamped files under log_dir/logs/.

**Encoding & progress**: Updated main encoding path to use -progress flag with parsed percentage output. Changed NOISE_THRESHOLD default to -50.0. Upgraded HEVC QSV to high-quality ICQ settings (global_quality=18, lookahead, etc.). Moved filter_complex scripts to temp/scripts/ for debugging.

**Code organization**: Extracted CLI parsing to src/cli.py, path utilities to src/prompts.py, renamed silence_utils.py to silence_detector.py. Normalized SDK responses to plain strings. Added error logging under temp/logs/errors/. Updated default model to gemini-2.5-flash-lite:nitro.

**Target-length refinements**: Added threshold sweep + padding tuning with segment truncation safeguard, then removed truncation (output may exceed target). Documented in ALGO.md with examples.

**Constants extraction**: Added src/constants.py for all non-secret constants. Reduced src/config.py to env-backed secrets only. Updated imports across main.py, cli.py, paths.py, trim.py, detector.py, transcription/openrouter.py. Updated cleanup script for new directory structure.

---

## Recent entries (75-84, kept intact)

- `src/transcription/openrouter.py`, `src/titles/openrouter.py`: Hard-coded OpenRouter model defaults to google/gemini-2.5-flash-lite:nitro instead of reading from env-backed config.
- `README.md`: Updated configuration and model sections to state that only the API key uses environment variables; other knobs are CLI flags or code constants.
- `.env.example`: Clarified that only OPENROUTER_API_KEY should be set via environment; all other settings are CLI/config-based.
- `src/constants.py`: Added a dedicated module for all non-secret constants (silence defaults, target-mode thresholds, directories, extensions, bitrate/padding limits).
- `src/config.py`: Now only contains env-backed secret loading/validation; removed all constant definitions from this module.
- `main.py`, `src/cli.py`, `src/paths.py`, `src/trim.py`, `src/silence/detector.py`, `src/transcription/openrouter.py`: Updated imports to use `src.constants` instead of `src.config` for non-secret constants.
- `pwsh/Cleanup-ProcessedFiles.ps1`: Updated cleanup to delete only `output/` (temp now lives under `output/temp`) while still moving `raw/` files to `archive/`.
- `ALGO.md`: Updated documentation to match current target-mode (threshold sweep + padding tuning) and to describe padding/inputs the way segments are actually built in `src/trim.py` / `src/silence/detector.py`.
- `ALGO.md`: Added concrete examples illustrating how threshold/min_duration/padding change results and a worked target-mode sweep + padding tuning walkthrough.
- `ALGO.md`: Corrected examples to reflect the "skip silences ≤ 2×pad" rule, avoid threshold-equality ambiguity, and match `find_optimal_padding`'s strict "< target" behavior.
- `src/titles/openrouter.py`: Added deterministic post-processing to normalize/dedupe repeated `ﷺ` when Prophet epithets appear consecutively.
- `src/prompts.py`: Fixed the `المصطفى` spelling in the honorific-enrichment prompt examples.
- `src/constants.py`: Added precision controls for trim timestamp precision and target-mode padding tolerance/step sizing.
- `src/silence/detector.py`: Centralized timestamp normalization and precision-aware segment length/padding calculations, plus precision-aware `find_optimal_padding`.
- `src/silence_detector.py`: Re-exported `normalize_timestamp` for compatibility through shim imports.
- `src/trim.py`: Reused shared normalization in segment construction and target/no-target boundary handling for consistent timing.
- `README.md`: Documented trimming precision configuration knobs in `src/constants.py`.
- `ALGO.md`: Updated trimming precision behavior and `PAD_INCREMENT_SEC` target-mode impact.
- `src/ffmpeg_utils.py`: Added `add_filter_complex_script` helper to use FFmpeg's non-deprecated `-/filter_complex` script input syntax.
- `src/trim.py`: Switched filter graph script injection from deprecated `-filter_complex_script` to `-/filter_complex`, and updated related debug labels.
- `README.md`: Added note that FFmpeg now uses `-/filter_complex` and should not emit deprecation warnings.

- `src/trim.py`: Consolidated target and non-target trimming through a single segment-planning path that resolves effective thresholds, min durations, and padding before segment construction.
- `ALGO.md`: Clarified that both target and non-target flows share the same segment-builder pipeline, with different padding selection behavior for target mode.
- `src/trim.py`: Removed libx264 fallback logic so both normal and minimal fallback encoding paths now use a single hevc_qsv attempt.
- `README.md`: Updated encoding behavior documentation to reflect single-encoder `hevc_qsv` flow and direct failure without codec fallback.
