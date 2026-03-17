# Session change summaries for AI agents

Entries below are appended by the agent after making code or config changes.

## Condensed older entries (1-74)

- Configuration and constants cleanup: moved from scattered global defaults to secret-only `.env` usage (`OPENROUTER_API_KEY` only), added a dedicated `src/constants.py`, and switched core modules to import constants from it.
- OpenRouter migration: replaced direct HTTP usage with the official SDK, introduced shared request/retry and logging flow, and standardized default model behavior for transcription and title generation.
- Silence detection and title flow: reworked segment detection/trimming with adaptive threshold + padding strategies, made timestamp handling consistent, and refined honorific-aware title generation.
- Architecture and compatibility refactor: added module shims for openrouter/transcription/silence paths, split CLI/path/prompt responsibilities, and normalized SDK response handling.
- Encoding and media pipeline modernization: migrated FFmpeg script injection to `-/filter_complex`, added progress parsing, tuned HEVC-QSV settings, and reorganized temp/log/debug artifact layout.
- Documentation and cleanup alignment: updated `README.md`, `ALGO.md`, `.env.example`, and cleanup scripts to match the new architecture and runtime behavior.

## Recent entries (75-84, kept intact)

- `src/transcription/openrouter.py`, `src/titles/openrouter.py`: Hard-coded OpenRouter model defaults to google/gemini-2.5-flash-lite:nitro instead of reading from env-backed config.
- `README.md`: Updated configuration and model sections to state that only the API key uses environment variables; other knobs are CLI flags or code constants.
- `.env.example`: Clarified that only OPENROUTER_API_KEY should be set via environment; all other settings are CLI/config-based.
- `src/constants.py`: Added a dedicated module for all non-secret constants (silence defaults, target-mode thresholds, directories, extensions, bitrate/padding limits).
- `src/config.py`: Now only contains env-backed secret loading/validation; removed all constant definitions from this module.
- `main.py`, `src/cli.py`, `src/paths.py`, `src/trim.py`, `src/silence/detector.py`, `src/transcription/openrouter.py`: Updated imports to use `src/constants` instead of `src.config` for non-secret constants.
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
