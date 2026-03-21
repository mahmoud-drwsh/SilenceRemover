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
