# Session change summaries for AI agents

After code or config changes, agents append short notes here. When this file grows past ~50 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Agent workflow

When the environment supports delegated agents (subagents), **prefer routing simple, well-bounded work** to them—e.g. targeted repo search, a single-file change, a one-off shell or git task, or a narrow “find and report” exploration—so the **supervising agent** keeps a smaller context: it synthesizes outcomes instead of loading every tool trace and file dump into its own window.

## Condensed changelog

- **Config & layout**: `.env` holds secrets (e.g. `OPENROUTER_API_KEY`); shared defaults live in `src/core/constants.py`. Packages: `src/core`, `src/media`, `src/llm`, `src/ffmpeg`, `src/startup`; orchestration in `src/app/pipeline.py`. Legacy top-level shim modules were removed.
- **Root-level transcription**: `openrouter_transport/` (root) — moved from `src/llm/client.py`, shared transport for chat requests. `sr_transcription/` (root) — `transcribe_and_save` API, prompt, format validation; imports from `openrouter_transport` and `src.core.constants` for AUDIO_FORMATS. `src/llm/audio_for_llm.py` — FFmpeg-only audio extraction (no OpenRouter calls). Backward-compatible re-exports via `src/llm/__init__.py`. `pyproject.toml` now has Hatchling build system with explicit `packages = ["src", "sr_transcription", "openrouter_transport"]`.
- **Planning doc**: `PLAN.md` holds the full plan for root-level transcription encapsulation (`openrouter_transport`, transcription package, wiring, Hatchling, scope, manual verification).
- **FFmpeg layer**: Central builders, runners (including progress parsing), probing, silencedetect helpers, filter-graph utilities, and transcode command assembly. Scripted graphs use `-/filter_complex`; legacy `-filter_complex_script` fallback was dropped (FFmpeg 8+ assumed). **Silencedetect**: chained primary+edge in one decode when stderr exposes two filter labels (`detect_primary_and_edge_silence_points`); fallback to two passes; **skip** silencedetect when there is no audio stream; silence parse uses `run(..., capture_output=True)` (fixes subprocess usage on audio-only paths). **Video-only inputs**: lavfi-backed concat graphs, silent-audio generation, and related transcode helpers.
- **Encoding**: `src/ffmpeg/encoding_resolver.py` picks a runnable hardware HEVC profile (e.g. QSV, VideoToolbox) via probes/smoke tests; startup fails fast if none work; the resolved profile is passed into trim to avoid resolving again.
- **Silence & trim**: `TrimPlan` / `build_trim_plan` unify target vs non-target policies. `prepare_silence_intervals_with_edges` uses the combined silencedetect pass and shares edge normalization across snippet, target, and non-target paths; target-threshold sweep reuses the last sweep result instead of re-running `prepare_*` in the `for`/`else` branch. Edge re-scan uses a relaxed threshold and a short keep buffer at file ends. Constants: `TARGET_*`, `NON_TARGET_*`, `SNIPPET_*`. CLI requires positive `--target-length` and `--min-duration`; target mode supports threshold overrides and truncation when a target duration cannot be met.
- **Transcription snippet**: Phase 1 uses `create_silence_removed_snippet` with fixed snippet constants (ignores `--noise-threshold` / `--min-duration`); max length `SNIPPET_MAX_DURATION_SEC` (180s). Snippet path reuses the same edge policy as final trim.
- **Transcription audio**: Extraction pipeline favors OGG for the audio sent to the transcription model.
- **Pipeline run**: Always executes phases 1–3 (transcription, title, final MP4); hardware encoder is resolved at startup. The former `--llm-only` mode, `temp/titles.txt` run log, and `pwsh/Start-VerticalLlmDryRun.ps1` were removed.
- **Transcript gating**: `transcribe_and_save` does not write a file when the model returns empty/whitespace-only text (`RuntimeError`). `is_transcript_done` requires a transcript file with non-whitespace UTF-8 content (invalid UTF-8 is treated as not done). Phases 2–3 require a usable transcript before title/output.
- **LLM client**: OpenRouter requests default to capping input/context and output size (10k tokens each), with compatibility handling if the API rejects some fields.
- **Default models**: Transcription and title flows default to `google/gemini-3.1-flash-lite-preview` on OpenRouter unless callers override.
- **Title generation**: Prompts require verbatim, beginning-only title spans from the full transcript. One model call emits a small JSON array of candidates; one call returns per-candidate `verbatim_score` and `correctness_score`; highest combined score wins with deterministic tie-breaks. **No** separate honorific add/check LLM step after selection.
- **Phase 3 title overlay**: Pipeline passes `title_path` / `title_font` into trim; forces encode (no stream copy) when overlay is used. **PNG overlay** (`src/media/title_overlay.py`): Google Fonts CSS2 + TTF cache; Pillow render; Arabic via `arabic-reshaper` + `python-bidi`; filter graph uses PNG concat with `shortest=1`. **Layout**: sixths-based band (e.g. H/6–H/3), multi-line `_best_multi_line_layout` (max lines + combination cap), readability thresholds, `TITLE_TWO_LINE_MIN_GAIN_PX`, bbox-based metrics (`textbbox`, `anchor="lt"`) to avoid edge bleed. **Metadata**: final MP4 `comment` = source filename for editor-driven cleanup; legacy `SILENCE_REMOVER_SOURCE` still matched. **CLI**: `--title-font`.
- **Title editor**: FastAPI app (`src/app/title_editor_server.py`) with `TitleEditorLayout` (`src/startup/title_editor_layout.py`); `serve_titles.py` + `pwsh/Start-VerticalTitleEditor.ps1`; probe duplicate server, save JSON, full-width table UI, `textarea` titles, retry writes on Windows locks. On title change, delete final MP4s whose tags match source (`read_format_tags`, NFC + case-insensitive `comment` matching). Pipeline starts editor after bootstrap or skips if `/status` matches; no embedded uvicorn in pipeline. Dependencies: `fastapi`, `uvicorn`, Pillow, arabic reshaper/bidi.
- **Documentation**: `README.md` and `ALGO.md` cover architecture, CLI, snippet/edges, encoding, title rules, overlay geometry, and video-only behavior.

## Latest session edits

- `AGENTS.md`: Added **Agent workflow** guidance to prefer subagents for simple, contained tasks so the supervising agent’s context stays lean.
- `AGENTS.md`: Re-condensed per-file history into the thematic bullets above (file exceeded ~50 lines).
- `src/llm/__init__.py` / `sr_transcription/__init__.py`: Added trailing newline at EOF after agent commit review.
- `src/core/cli.py`: Removed `--llm-only`.
- `src/startup/bootstrap.py`: Removed `llm_only` from `StartupContext`; encoder is always resolved via `resolve_video_encoder()`.
- `src/app/pipeline.py`: Single three-phase `run()` path; removed titles.txt helpers, console LLM dump, `llm_only` on `run_title_phase`, and unused `transcribe_single_video`; `run_output_phase` requires `encoder`; Phase 2/3 preconditions require transcript before title/output.
- `README.md` / `PLAN.md` / `AGENTS.md`: Removed LLM-only / `titles.txt` documentation.
- `pwsh/Start-VerticalLlmDryRun.ps1`: Deleted (was only for `--llm-only`).
- `src/llm/client.py`: Deleted duplicate OpenRouter client; `openrouter_transport/` is the only implementation.
- `openrouter_transport/client.py`: `request()` docstrings describe `log_dir/logs/` (and `logs/errors/`); removed unused `timezone` import and unused log filename constant.
- `sr_transcription/api.py`: `log_dir` Args documented to match transport logging.
- `src/llm/title.py`: `log_dir` Args documented to match transport logging.
- `pyproject.toml`: Project name set to `silence-remover` (replacing `hucck`).
- `uv.lock`: Refreshed for renamed workspace package.
- `PLAN.md`: Marked encapsulation work complete—status section, checked scope list, current paths (`audio_for_llm`, no `src/llm/client.py`), and revised historical sections to match the tree; mermaid/layout labels use `sr_transcription`.
- `sr_transcription/api.py`: `transcribe_and_save` raises `RuntimeError` and does not write when the model returns empty/whitespace-only text.
- `src/core/paths.py`: `is_transcript_done` requires non-empty transcript content; catches `UnicodeDecodeError` as well as `OSError`.
- `README.md`: Five-stage “How it works”; merged Phase 3 overlay + renaming section; video-only and process-tracking text aligned with transcript gating.
- `temp/test_openrouter.py`: Uses `transcribe_with_openrouter` from `sr_transcription` instead of raw `requests`; `extract_first_minute_audio` docstring/`fmt` param aligned with ogg+m4a only.
- `README.md`: “How it works” intro set to **four** stages to match four `###` sections (post-review fix).
