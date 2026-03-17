# Session change summaries for AI agents

Entries below are appended by the agent after making code or config changes.

## Condensed entries (1-84)

- Refactored configuration and runtime constants so `.env` only stores secrets (`OPENROUTER_API_KEY`), `src/constants.py` owns non-secret defaults, and dependent modules now import shared constants consistently.
- Migrated OpenRouter integration in transcription/title flows to the SDK with shared request/retry/logging behavior and standardized default model selection.
- Reworked silence and trim behavior around a unified segment-planning pipeline with adaptive threshold/padding, timestamp normalization, precision tuning, and consistent target-mode handling.
- Modernized FFmpeg and media pipeline execution with `-/filter_complex`, progress parsing, HEVC-QSV-focused encoding behavior, and a reduced fallback surface.
- Improved interoperability and maintainability through compatibility shims, import/path cleanup, and refined CLI/prompt responsibilities.
- Updated supporting docs and tooling (`README.md`, `ALGO.md`, `.env.example`, cleanup script) to match current architecture and behavior, plus small quality fixes in prompts and title post-processing.
- `AGENTS.md`: Compressed this changelog section into a smaller thematic summary while preserving the key implementation milestones.
- `.cursor/rules/summarize-to-agents-md.mdc`: Added a retention instruction to summarize AGENTS.md entries when file size grows above 50 lines.
- `src/encoding_resolver.py`: Added a strict encoder resolver with a shared `VideoEncoderProfile` contract and HEVC-QSV defaults for central codec selection.
- `src/trim.py`: Replaced hardcoded `hevc_qsv` flag lists with resolved encoder profiles for both minimal-fallback and normal video encoding paths.
- `README.md`: Updated encoding documentation to describe resolver-driven default selection and future hardware encoder extensibility.
- `src/encoding_resolver.py`: Added `hevc_videotoolbox` to the encoder resolution chain so HEVC VideoToolbox is supported when available.
- `src/encoding_resolver.py`: Changed resolver behavior to probe encoders in order with a minimal FFmpeg encode test and cache the first runnable profile.
- `main.py`: Added early startup encoder resolution at startup, failing fast if no runnable hardware encoder is found.
- `src/encoding_resolver.py`: Added `-q:v 25` for the `hevc_videotoolbox` profile so videotoolbox quality is explicitly set to 25.
