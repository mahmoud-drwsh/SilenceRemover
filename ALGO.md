# Silence-removal algorithm

## Target mode: bounded natural-pause budgeting

`--target-length` is an **exclusive** limit: use `180` for below three minutes.
The live planner in `packages/sr_trim_plan/api.py` uses the fixed-detector,
integer-microsecond allocator in `packages/sr_trim_plan/pause_budget.py`.
See the [research, rationale, and listening protocol](docs/research/natural-pause-budget.md).

1. Detect raw quiet intervals once at −50 dB and a 0.6-second minimum.
   Do not raise the threshold to make a duration target achievable.
2. Keep existing gaps at or below 0.6 seconds unchanged. Longer internal gaps
   have a 0.6-second floor and a 1.2-second preferred cap. Edge gaps retain up
   to 0.2 seconds adjacent to speech. These are engineering defaults,
   not a scientifically universal Arabic minimum.
3. Reserve 0.5 seconds below the requested limit. If protected content plus
   pause floors exceeds that budget, raise `TargetDurationUnreachable`.
   Never truncate or return over-target success.
4. If the capped timeline fits, retain it. Otherwise distribute the available
   pause budget proportionally to each gap's slack above its floor.
5. Cut from pause interiors, keeping half the allocated internal gap next to
   each speech boundary. Apply identical audio/video intervals and reset their
   timestamps. Do not add synthetic gaps between words.
6. Probe before final acceptance and before upload after subtitle muxing.
   Reject duration greater than or equal to the target. Headroom is not a bound
   for every frame rate/cut count; no speech-cutting `-t` fallback is used.

Sources already below target are analyzed for the long-pause cap. Analysis
failures propagate; entirely detected silence is held for manual review.
Material outside detected silence is preserved, but energy classification is
not proof that a region contains no quiet speech.

Legacy binary-search helpers remain for compatibility, not live target mode.
Target script cache keys include policy/version. Previously completed outputs
and server approvals require deliberate reprocessing with fresh review.

## Non-target and snippet processing

Non-target mode retains its detector/edge policy and segment builder, with
noise threshold, minimum duration, and padding overrides. In that legacy
builder a cut gap retains `pad_sec` before the next speech segment; gaps no
longer than `2 * pad_sec` are skipped. This is not two-sided padding.
Snippet-only extraction keeps its existing policy; snippets derived from a
final trim script follow that script's timeline.

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
