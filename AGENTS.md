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
- `src/ffmpeg/__init__.py`: Added a package API to expose centralized ffmpeg builders, probing, detection, filter graph, and transcode helpers.
- `src/ffmpeg/core.py`: Centralized `ffmpeg`/`ffprobe` base command and script/filter utilities used by all modules.
- `src/ffmpeg/runner.py`: Added unified FFmpeg command runners for checked execution and `-progress` streaming parsing.
- `src/ffmpeg/probing.py`: Centralized duration/bitrate probes, encoder discovery, and encoder smoke-test checks.
- `src/ffmpeg/detection.py`: Moved silencedetect command construction/parsing into dedicated ffmpeg detection helpers.
- `src/ffmpeg/filter_graph.py`: Moved audio/video concat filter-graph generation and script-write helpers into dedicated functions.
- `src/ffmpeg/types.py`: Added shared typing contracts for ffmpeg execution helpers.
- `src/ffmpeg/transcode.py`: Consolidated extraction, minimal-output, and final-trim command builders used by transcription and trimming flows.
- `src/encoding_resolver.py`: Switched resolver probing path to `src/ffmpeg/probing.py` and kept profile-based codec orchestration intact.
- `src/silence/detector.py`: Routed silence detection through centralized ffmpeg detection helper and retained algorithm APIs.
- `src/trim.py`: Routed probing, audio trim graph construction, and all ffmpeg execution through centralized ffmpeg modules and runners.
- `src/transcription/openrouter.py`: Replaced inline ffmpeg extraction command execution with centralized transcode command builders and runner execution.
- `src/content.py`: Updated imports away from legacy top-level `src.title`/`src.transcribe` shim modules to package-based imports.
- `src/transcribe.py`: Removed legacy compatibility shim module in favor of direct `src.transcription` imports.
- `src/title.py`: Removed legacy compatibility shim module in favor of direct `src.titles` imports.
- `src/silence_detector.py`: Removed legacy compatibility shim module in favor of direct `src.silence.detector` imports.
- `src/app/__init__.py`: Added package entrypoints for pipeline orchestration exports.
- `src/core/`: Moved configuration, constants, paths, CLI, filesystem, and filename utilities into the new package namespace.
- `src/llm/`: Moved OpenRouter client, prompts, transcription, and title flows under `src/llm` with updated imports.
- `src/media/`: Moved silence detection and trim logic under `src/media` and rewired runtime imports.
- `src/app/pipeline.py`: Consolidated phase orchestration, replacing legacy content-centric flow and simplifying `main.py` to call the pipeline entrypoint.
- `main.py`, `README.md`, and stale import sweep: Wired entrypoint to `src.app.pipeline.run`, updated architecture docs, and removed stale legacy modules/directories.
