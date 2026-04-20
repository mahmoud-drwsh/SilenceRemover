# Silence-removal algorithm

This document describes how silence is detected and how the trimmed output length is controlled.
When a target length is set, the code sweeps thresholds (multiple detection passes) and then tunes padding.

## Basics

- **Silence detection** uses FFmpeg’s `silencedetect` filter: `silencedetect=n={noise_threshold}dB:d={min_duration}`.
- **noise_threshold (dB):** Must be negative. Audio below this level is considered silence. **Higher** (e.g. -20) = more is treated as silence = **shorter** output. **Lower** (e.g. -50) = only very quiet parts = **longer** output.
- **min_duration (s):** Minimum length of a quiet stretch to count as silence. **Lower** (e.g. 0.2) = short pauses removed = **shorter** output. **Higher** (e.g. 2.0) = only long gaps = **longer** output.
- **Padding:** The same segment-builder is used in both modes. For each detected silence, segment-building keeps up to `pad_sec` seconds *before the silence ends* (i.e., it starts the next kept segment at `silence_end - pad_sec`). In addition, silences with **duration ≤ 2 × pad_sec** are treated as non-silence (skipped), merging adjacent speech across very short gaps. **More padding** = **longer** output.
- **Precision policy:** Segment boundaries and length calculations are normalized to `TRIM_DECIMAL_PLACES` and compared against `TRIM_TIMESTAMP_EPSILON_SEC` from `src/core/constants.py`.

Segments to keep are built from (silence_starts, silence_ends) and padding; the concatenation of those segments is the trimmed duration.

## Phase 1: Snippet extraction

Phase 1 always creates a fixed-rule snippet for transcription:

- Silence detection runs once with `silencedetect=n=-55dB:d=0.01` (`SNIPPET_NOISE_THRESHOLD_DB` + `SNIPPET_MIN_DURATION_SEC` semantics).
- Leading and trailing edge silences are rescanned using the shared `prepare_silence_intervals_with_edges` policy, and only the edge intervals are replaced before trimming.
- Leading/trailing edges are then reduced to the 200ms keep buffer via shared edge normalization.
- `pad_sec` is still applied through the shared segment-builder.
- The resulting audio is capped to `SNIPPET_MAX_DURATION_SEC` (180 seconds / 3 minutes by default) after concatenation.
- This phase is intentionally independent of CLI `--noise-threshold`, `--min-duration`, and `--target-length` settings.

## Examples (intuition)

### Example A: How `noise_threshold` and `min_duration` change what counts as silence

Suppose a 60s clip has these quiet stretches (level shown as approximate loudness):

- 10.0–10.3s at **-46 dB** (0.3s)
- 20.0–21.0s at **-70 dB** (1.0s)
- 40.0–40.4s at **-48 dB** (0.4s)

Now compare two settings:

- **Less aggressive**: `noise_threshold=-60dB`, `min_duration=0.5s`
  - Only the 20.0–21.0s stretch qualifies (quiet enough and long enough).
  - Result: only that 1.0s gap can be removed (plus whatever padding you add back).
- **More aggressive**: `noise_threshold=-45dB`, `min_duration=0.2s`
  - All three stretches qualify (threshold is higher and min duration is lower).
  - Result: more is removed, so the output gets shorter.

### Example B: How padding affects segment boundaries

One detected silence: `silence_start=20.0`, `silence_end=22.0`, `pad_sec=0.5`.

- Without padding (`pad_sec=0`), the next kept segment starts at 22.0s.
- With padding (`pad_sec=0.5`), the next kept segment starts at \(22.0 - 0.5 = 21.5\)s, preserving the last 0.5s before the silence ended.
- If the silence duration is ≤ \(2 \times pad\), we skip cutting it entirely (merge across it). For example, `silence_start=20.0`, `silence_end=21.0`, `pad_sec=0.5` has duration \(1.0 \le 1.0\), so there is **no cut** for that gap.

## When no target length is set

- For final output trim in non-target mode, `--noise-threshold` / `--min-duration` (if provided) are used; otherwise defaults from `src/core/constants.py` are used (`NON_TARGET_NOISE_THRESHOLD_DB=-50.0`, `NON_TARGET_MIN_DURATION_SEC=1.0`).
- Before padding is applied, the non-target flow runs `prepare_silence_intervals_with_edges` (`EDGE_RESCAN_THRESHOLD_DB` / `EDGE_RESCAN_MIN_DURATION_SEC`) which replaces only the primary leading/trailing silence intervals and retains `EDGE_SILENCE_KEEP_SEC` (0.2s) at each edge.
- Segment build flow is shared with target-mode: detect silences -> build keep segments -> concat.
- In non-target mode, `pad_sec` is fixed to `NON_TARGET_PAD_SEC` from `src/core/constants.py` (no CLI override).

## When target length is set (`--target-length`)

When target length is set, the live planner uses the fixed search constants in `src/core/constants.py`:

- `TARGET_SEARCH_LOW_DB = -60.0`
- `TARGET_SEARCH_HIGH_DB = -40.0`
- `TARGET_SEARCH_STEP_DB = 0.1`
- `TARGET_SEARCH_MIN_SILENCE_LEN_SEC = 0.2`
- `TARGET_SEARCH_BASE_PADDING_SEC = 0.2`
- `TARGET_SEARCH_PADDING_STEP_SEC = 0.01`

### Overview

Goal: preserve as much silence as possible while trying to stay at or under the target length, without truncating content.

The live planner always uses a two-stage binary search:

1. **Threshold search:** binary-search the threshold grid from `-60.0` to `-40.0` dB, always evaluating with `min_silence_len=0.2s` and `padding=0.2s`.
2. **Padding search:** once a threshold can meet the target, binary-search padding on a `0.01s` grid to find the largest value that still stays at or under target.

If no threshold can reach target, the planner returns the best-effort over-target plan built from `-40.0 dB` and `0.2s` padding. There is no truncation fallback.

### Steps

1. **Edge scan once:** run `detect_edge_only_cached(...)` a single time and reuse its result across the full target-mode search.

2. **Threshold probe:** for each threshold sample, run `detect_primary_with_cached_edges(...)` with:
   - `primary_min_duration=0.2`
   - `primary_noise_threshold=<sampled threshold>`
   - the cached edge intervals from step 1
   - file-backed primary detection caching still enabled when `temp_dir` is available

3. **Estimate length at base padding:** compute
   - `calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.2)`
   - If the probe cannot be evaluated, treat that branch as overshoot and continue searching toward more aggressive thresholds.

4. **Select threshold:** choose the earliest threshold whose estimated output is `<= target`.
   - If none qualify, use `-40.0 dB` as the final fallback threshold and keep padding at `0.2s`.

5. **Padding search:** for reachable target cases, reuse the selected threshold’s already-detected silence intervals and estimate lengths with `calculate_resulting_length(...)` only.
   - Start from `0.2s`
   - Expand upward geometrically to find an upper bound
   - Binary-search the `0.01s` grid for the largest valid padding
   - If a padding probe is invalid, treat it as overshoot
   - If no safe expansion exists, fall back to `0.2s`

6. **Build segments:** build the final keep segments from the selected silence intervals and the resolved padding. No truncation step runs after this.

### Example C: Target-mode binary search (end-to-end)

Assume:

- Original duration = 120.0s
- Target length = 90.0s
- Threshold grid = `[-60.0, -59.9, -59.8, ..., -40.0]` dB
- `min_silence_len = 0.2s`
- Base padding = `0.2s`

Threshold search evaluates each probe with `pad=0.2s`:

- At **-60 dB**, base result is 98.0s → **too long** (98 > 90), continue.
- At **-55 dB**, base result is 92.0s → **too long**, continue.
- At **-50 dB**, base result is 88.0s → **meets target** (88 ≤ 90), choose **-50 dB**.

Padding search then reuses the `-50 dB` silence intervals and pushes padding upward:

- `pad=0.20` → 89.4s (**< 90.0**, still under)
- `pad=0.40` → 89.9s (**< 90.0**, still under)
- `pad=0.41` → 90.01s (**> 90.0**, overshoot) ⇒ choose `pad=0.40`

Final settings used for segment building: `noise_threshold=-50.0 dB`, `min_duration=0.2s`, `pad_sec=0.40s`.

### Edge cases

- **Target length ≥ original duration:** Output is a copy of the input (no detection).
- **No silences:** Every threshold probe resolves to the full duration, so the planner falls back to `-40.0 dB` with `0.2s` padding and returns the full file as best effort.
- **Padding search cannot expand safely:** padding stays at `0.2s`.
- **A threshold or padding probe is invalid:** that branch is treated as overshoot during search.

## Shared flow across modes

- Both target and non-target paths now use the same segment-builder implementation.
- The mode difference is how `pad_sec` is selected and what detection parameters are used:
  - Both modes now use the same shared edge-normalization helper (`prepare_silence_intervals_with_edges`) to apply edge replacement/trimming.
  - Non-target mode: fixed `noise_threshold`, `min_duration`, and `pad_sec` (`NON_TARGET_PAD_SEC`) with the shared edge helper applied before padding.
  - Target mode: fixed-parameter threshold search + padding search, with `min_duration=0.2s`, `base_padding=0.2s`, and the shared edge helper applied before each candidate length evaluation.

Implementation: `binary_search_threshold(...)` and `binary_search_padding(...)` live in `packages/sr_trim_plan/api.py`, alongside trim-plan assembly. The legacy `sr_threshold_selection` package remains for compatibility, but it is no longer the live target-mode planner.

## Title overlay PNG (`packages/sr_title_overlay/`)

Phase 3 burns in a **pre-rendered RGBA PNG** (not FFmpeg `drawtext`). The pipeline probes the source with `ffprobe`, then builds a strip image of size **`video_width × banner_height`**, where `banner_height = max(1, int(video_height * TITLE_BANNER_HEIGHT_FRACTION))` with **`TITLE_BANNER_HEIGHT_FRACTION = 1/6`**. That PNG is composited at **`overlay_x=0`, `overlay_y=int(video_height * TITLE_BANNER_START_FRACTION)`** with **`TITLE_BANNER_START_FRACTION = 1/6`** (top of the second sixth), so the covered band is **`y ∈ [H/6, H/3]`** on the full frame. Implementation: `trim.py` → `sr_title_overlay.build_title_overlay` → FFmpeg `overlay=0:{overlay_y}` in `src/ffmpeg/filter_graph.py`.

### Text normalization (Arabic / RTL)

- Input is whitespace-collapsed (`" ".join(title.split())`).
- Pillow draws in visual order only, so each **logical** line is passed through `arabic-reshaper` then `python-bidi` `get_display` (`_line_for_pillow`) before measurement and drawing.

### Layout box (inner margin)

Inside the PNG, text must fit in:

- **max_width** = `max(1, video_width × 0.95)`
- **max_height** = `banner_height × 0.95`

The strip is filled with a semi-transparent black (`TITLE_BANNER_BG_ALPHA` in `packages/sr_title_overlay/constants.py`, default 0.5).

### Font

- `--title-font` selects a Google Font family; the TTF is downloaded once and cached under `temp/fonts/` (see `get_font_cache_path`).

### Font size: largest fit (binary search)

1. **Single-line reference:** After shaping, the whole title is one display string. `_estimate_font_size_upper_bound` derives a coarse upper bound from pixel width at a reference size; `_largest_fitting_font_size` binary-searches the largest integer size such that `_lines_fit` returns true.
2. **`_lines_fit`:** For a candidate size, every display line’s **ink width** must be ≤ `max_width`, and the **stacked block height** must be ≤ `max_height`. Width uses `textbbox(..., anchor="lt")` width (not `textlength`), so Arabic glyph bounds match what is drawn. Height is the sum of each line’s bbox height plus an inter-line gap `max(4, int(font_size * 0.1))` between lines—matching the draw loop.

`_largest_fitting_font_size` returns **0** if nothing fits; the builder may skip writing a visible overlay in that edge case.

### Multi-line word-boundary search (multi-word titles)

If there are at least two words, the code evaluates **word-boundary layouts** with **2 to `TITLE_OVERLAY_MAX_LINES`** logical lines (default **5**, `packages/sr_title_overlay/constants.py`). For each line count `k`, it enumerates all `(k-1)`-cut compositions of the `n` words (`itertools.combinations` over the `n-1` inter-word gaps). For each candidate, lines are shaped and `_largest_fitting_font_size` finds the largest font that fits. The winner maximizes **fitted font size**; ties favor **lower variance** of per-line character counts, then **more lines** when variance is equal (so extra vertical space can go toward readability). If `C(n-1, k-1)` exceeds **`TITLE_OVERLAY_MAX_LAYOUT_COMBINATIONS`** (default **8000**), that `k` is skipped to bound work.

The chosen layout replaces single-line **only if** `multi_line_size >= single_line_size + TITLE_TWO_LINE_MIN_GAIN_PX` (default **1**, same module). This prefers more lines when they yield a larger fitted font (e.g. more room to use banner height).

### Greedy wrap (when still single-line)

If no multi-line upgrade applies, words are wrapped greedily at the chosen `font_size` using the same pixel-width rule until each line fits `max_width`.

### Final safety pass

If the wrapped lines no longer fit at the current size (e.g. after wrapping), `_largest_fitting_font_size` is run again on the **final** line list with `hi` capped to the current size; if the result is 0, the overlay is skipped.

### Drawing

- Lines are drawn with **`anchor="lt"`** so `textbbox` metrics match the draw positions.
- **Horizontal:** Each line is centered using `x = (video_width - ink_w) / 2 - bb[0]` so the ink box is centered (not advance-width centering).
- **Vertical:** Lines are stacked top-to-bottom with the same gap as in `_stacked_text_block_height`, starting at `y` so the block is vertically centered in the banner.

### Tunables

- **PNG renderer** (`packages/sr_title_overlay/constants.py`): `TITLE_BANNER_BG_ALPHA`, `TITLE_TWO_LINE_MIN_GAIN_PX`, `TITLE_OVERLAY_MAX_LINES`, `TITLE_OVERLAY_MAX_LAYOUT_COMBINATIONS`.
- **Banner placement on frame** (`src/core/constants.py`): `TITLE_BANNER_START_FRACTION`, `TITLE_BANNER_HEIGHT_FRACTION`; default title font family for CLI: `TITLE_FONT_DEFAULT`.
- `TITLE_MIN_READABLE_FONT_PX` / `TITLE_MIN_READABLE_FONT_BANNER_FRACTION` — defined for potential future readability heuristics; the current overlay sizing logic uses the multi-line gain rule and `_lines_fit` only.

## Phase 3 video compositing: title + optional logo (`src/ffmpeg/filter_graph.py`)

After trim/concat, the video stream may receive one or two PNG overlays. Builders: `_overlay_suffix_after_concat` (normal path) and `build_minimal_encode_overlay_filter_complex` (minimal encode when all audio is silence).

### Demuxer input indices (FFmpeg `-i` order)

- **`0`:** Source video (after concat, this is `[outv]` from `concat` in the main graph; in the minimal graph it is `[0:v]`).
- **`1`:** Title overlay PNG when a title is rendered (prepared in Phase 5 and consumed during Phase 7 when overlays run).
- **`2`:** Logo PNG only when **both** title and logo are used. If `trim_single_video` runs with a logo but **no** title PNG, the logo is **`1`** instead.

### Stacking order (z-order)

**Logo is composited first, then the title strip**—the title remains visually on top. This matches the filter chain: logo `overlay` runs on the base video, then title `overlay` runs on that result.

### Logo scaling and alpha

- `ffprobe` reads the logo’s intrinsic width (failure skips the logo with a warning).
- Uniform scale targets display width **`video_width × LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO`** vs intrinsic width (`scale=w=iw*tw/lw:h=ih*tw/lw` in the graph).
- After `format=rgba`, **`colorchannelmixer=aa=LOGO_OVERLAY_ALPHA`** scales alpha before compositing.
- Position uses **`overlay=W-w-{m}:{m}`** with **`m = LOGO_OVERLAY_MARGIN_PX`** (top-aligned; with full frame width and `m=0`, `x` is `0`).

Constants: `DEFAULT_LOGO_PATH`, `LOGO_OVERLAY_*` in `src/core/constants.py`. Wiring: `src/media/trim.py` → `build_final_trim_command` / `build_minimal_video_command` in `src/ffmpeg/transcode.py`.
