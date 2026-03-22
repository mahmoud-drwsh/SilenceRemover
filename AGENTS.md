# Session change summaries for AI agents

After code or config changes, agents append short notes here. When this file grows past ~50 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Condensed changelog

- **Config & layout**: `.env` holds secrets (e.g. `OPENROUTER_API_KEY`); shared defaults live in `src/core/constants.py`. Packages: `src/core`, `src/media`, `src/llm`, `src/ffmpeg`, `src/startup`; orchestration in `src/app/pipeline.py`. Legacy top-level shim modules were removed.
- **Transcription packages** (`packages/`): `packages/openrouter_transport/` — shared transport for chat requests (was `src/llm/client.py`). `packages/sr_transcription/` — `transcribe_and_save` API, prompt, format validation; imports from `openrouter_transport` and `src.core.constants` for AUDIO_FORMATS. `src/llm/audio_for_llm.py` — FFmpeg-only audio extraction (no OpenRouter calls). Backward-compatible re-exports via `src/llm/__init__.py`. `pyproject.toml` Hatchling `packages` includes `src`, `packages/sr_transcription`, `packages/openrouter_transport` (wheel still exposes top-level `sr_transcription` / `openrouter_transport` imports).
- **Planning doc**: Historical encapsulation notes referred to `openrouter_transport` + `sr_transcription`; both modules now live under `packages/` with the same import names.
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
- **Phase 3 title overlay**: Pipeline passes `title_path` / `title_font` into trim; forces encode (no stream copy) when overlay is used. **PNG overlay** (`src/media/title_overlay.py`): Google Fonts CSS2 + TTF cache; Pillow render; Arabic via `arabic-reshaper` + `python-bidi`; filter graph uses PNG concat with `shortest=1`. **Layout**: sixths-based band (e.g. H/6–H/3), multi-line `_best_multi_line_layout` (max lines + combination cap), readability thresholds, `TITLE_TWO_LINE_MIN_GAIN_PX`, bbox-based metrics (`textbbox`, `anchor="lt"`) to avoid edge bleed. **Optional logo**: repo `logo/logo.png`, `colorchannelmixer` alpha, uniform `scale` to `video_w * LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO` vs intrinsic width, top-right margin; bad logo probe skips overlay with a warning. **Metadata**: final MP4 `comment` = source filename for editor-driven cleanup; legacy `SILENCE_REMOVER_SOURCE` still matched. **CLI**: `--title-font`.
- **Title editor**: FastAPI app in `src/title_editor/server.py` with `TitleEditorLayout` (`src/startup/title_editor_layout.py`); standalone runner `src/title_editor/standalone.py` (`run_title_editor_server`). Entry: `python main.py <input_dir> --title-editor` (pipeline unchanged otherwise); thin `serve_titles.py` shim + `pwsh/Start-VerticalTitleEditor.ps1`. Probe duplicate server, save JSON, full-width table UI, `textarea` titles, retry writes on Windows locks. On title change, delete final MP4s whose tags match source (`read_format_tags`, NFC + case-insensitive `comment` matching). Dependencies: `fastapi`, `uvicorn`, Pillow, arabic reshaper/bidi.
- **Documentation**: `README.md` and `ALGO.md` cover architecture, CLI, snippet/edges, encoding, title rules, overlay geometry, and video-only behavior.

## Latest session edits

- `src/core/constants.py`: Repo-root `DEFAULT_LOGO_PATH`, `LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO`, `LOGO_OVERLAY_MARGIN_PX`, `LOGO_OVERLAY_ALPHA`.
- `src/ffmpeg/filter_graph.py`: Title burn-in uses `format=rgba` (concat + minimal); optional logo chain (`colorchannelmixer`, uniform scale, top-right overlay); dynamic lavfi input index; `build_minimal_encode_overlay_filter_complex`.
- `src/ffmpeg/transcode.py`: Optional looping `logo_path` and alpha on `build_final_trim_command` / `build_minimal_video_command`.
- `src/media/trim.py`: Logo overlay when `logo/logo.png` exists; on logo probe failure warn and skip; copy shortcut unless title or logo; threads sizes/alpha into graphs.
- `README.md`: Logo FFmpeg input order (title at `1`, logo at `2` in Phase 3), resilient logo skip, `output/temp/…` paths and directory tree aligned with bootstrap.
- `.gitignore`: Ignore repo-root `logo/` so optional branding assets stay local.
- `AGENTS.md`: Condensed changelog logo note and this session block.
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
- `temp/test_openrouter.py`: Removed ad-hoc OpenRouter transcription smoke test.
- `temp/list_audio_models.py`: Removed ad-hoc OpenRouter models listing script.
- `README.md`: “How it works” intro set to **four** stages to match four `###` sections (post-review fix).
- `packages/sr_transcription/`: Relocated from repo root into `packages/`; import name unchanged (`sr_transcription`).
- `packages/openrouter_transport/`: Relocated from repo root into `packages/`; import name unchanged (`openrouter_transport`).
- `pyproject.toml`: Wheel `packages` list now points at `packages/sr_transcription` and `packages/openrouter_transport`.
- `README.md`: Transcription / domain-layout docs updated to `packages/…` paths.
- `AGENTS.md`: Condensed changelog updated for the `packages/` transcription layout.
- `.cursor/commands/review-commit-push.md`: Cursor slash command to run agent-assisted review, then commit and push only if checks pass.
- `src/title_editor/server.py`: FastAPI title editor UI (moved from deleted `src/app/title_editor_server.py`).
- `src/title_editor/standalone.py`: `run_title_editor_server` uvicorn entry (no pipeline).
- `src/title_editor/__init__.py`: Re-exports server helpers and standalone runner.
- `main.py`: Parses CLI; `--title-editor` runs only the title server, else runs pipeline with the same namespace.
- `src/core/cli.py`: Added `--title-editor` flag.
- `src/app/pipeline.py`: `run(args=None)` accepts a pre-parsed namespace from `main.py`.
- `serve_titles.py`: Compatibility wrapper calling `run_title_editor_server`.
- `pwsh/Start-VerticalTitleEditor.ps1`: Invokes `main.py … --title-editor`.
- `README.md`: Title editor usage, `--title-editor`, domain layout lists `src/title_editor`; intro line avoids a fixed package count.
- `AGENTS.md`: Title editor paths updated for `src/title_editor` package.
- `.cursor/commands/review-commit-push.md`: Review-and-commit slash command delegates scope, review, checks, and commit; no `git push` (user pushes manually); supervisor coordinates and synthesizes.

## Agent workflow

When the environment supports delegated agents (subagents), **prefer routing simple, well-bounded work** to them—e.g. targeted repo search, a single-file change, a one-off shell or git task, or a narrow “find and report” exploration—so the **supervising agent** keeps a smaller context: it synthesizes outcomes instead of loading every tool trace and file dump into its own window.