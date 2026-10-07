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
- This phase is intentionally independent of CLI `--non-target-noise-threshold`, `--non-target-min-duration`, and `--target-length` settings.

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

- For final output trim in non-target mode, `--non-target-noise-threshold` and `--non-target-min-duration` (if provided) are used; otherwise defaults from `src/core/constants.py` are used (`NON_TARGET_NOISE_THRESHOLD_DB=-50.0`, `NON_TARGET_MIN_DURATION_SEC=1.0`).
- Before padding is applied, the non-target flow runs `prepare_silence_intervals_with_edges` (`EDGE_RESCAN_THRESHOLD_DB` / `EDGE_RESCAN_MIN_DURATION_SEC`) which replaces only the primary leading/trailing silence intervals and retains `EDGE_SILENCE_KEEP_SEC` (0.2s) at each edge.
- Segment build flow is shared with target-mode: detect silences -> build keep segments -> concat.
- In non-target mode, `pad_sec` defaults to `NON_TARGET_PAD_SEC` from `src/core/constants.py` and can be overridden with `--non-target-pad-sec`.

## When target length is set (`--target-length`)

When target length is set, the live planner uses the fixed search constants in `src/core/constants.py`:

- `TARGET_SEARCH_LOW_DB = -60.0`
- `TARGET_SEARCH_HIGH_DB = -35.0`
- `TARGET_SEARCH_STEP_DB = 0.1`
- `TARGET_SEARCH_MIN_SILENCE_LEN_SEC = 0.100`
- `TARGET_SEARCH_BASE_PADDING_SEC = 0.060`
- `TARGET_SEARCH_PADDING_STEP_SEC = 0.01`

### Overview

Goal: preserve as much silence as possible while trying to stay at or under the target length, without truncating content.

The live planner always uses a two-stage binary search:

1. **Threshold search:** binary-search the threshold grid from `-60.0` to `-35.0` dB, always evaluating with `min_silence_len=0.100s` and `padding=0.060s`.
2. **Padding search:** once a threshold can meet the target, binary-search padding on a `0.01s` grid to find the largest value that still stays at or under target.

If no threshold can reach target, the planner returns the best-effort over-target plan built from `-35.0 dB` and `0.060s` padding. There is no truncation fallback.

### Steps

1. **Edge scan once:** run `detect_edge_only_cached(...)` a single time and reuse its result across the full target-mode search.

2. **Threshold probe:** for each threshold sample, run `detect_primary_with_cached_edges(...)` with:
   - `primary_min_duration=0.100`
   - `primary_noise_threshold=<sampled threshold>`
   - the cached edge intervals from step 1
   - file-backed primary detection caching still enabled when `temp_dir` is available

3. **Estimate length at base padding:** compute
   - `calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.060)`
   - If the probe cannot be evaluated, treat that branch as overshoot and continue searching toward more aggressive thresholds.

4. **Select threshold:** choose the earliest threshold whose estimated output is `<= target`.
   - If none qualify, use `-35.0 dB` as the final fallback threshold and keep padding at `0.060s`.

5. **Padding search:** for reachable target cases, reuse the selected threshold’s already-detected silence intervals and estimate lengths with `calculate_resulting_length(...)` only.
   - Start from `0.060s`
   - Expand upward geometrically to find an upper bound
   - Binary-search the `0.01s` grid for the largest valid padding
   - If a padding probe is invalid, treat it as overshoot
   - If no safe expansion exists, fall back to `0.060s`

6. **Build segments:** build the final keep segments from the selected silence intervals and the resolved padding. No truncation step runs after this.

### Example C: Target-mode binary search (end-to-end)

Assume:

- Original duration = 120.0s
- Target length = 90.0s
- Threshold grid = `[-60.0, -59.9, -59.8, ..., -35.0]` dB
- `min_silence_len = 0.100s`
- Base padding = `0.060s`

Threshold search evaluates each probe with `pad=0.060s`:

- At **-60 dB**, base result is 98.0s → **too long** (98 > 90), continue.
- At **-55 dB**, base result is 92.0s → **too long**, continue.
- At **-50 dB**, base result is 88.0s → **meets target** (88 ≤ 90), choose **-50 dB**.

Padding search then reuses the `-50 dB` silence intervals and pushes padding upward:

- `pad=0.20` → 89.4s (**< 90.0**, still under)
- `pad=0.40` → 89.9s (**< 90.0**, still under)
- `pad=0.41` → 90.01s (**> 90.0**, overshoot) ⇒ choose `pad=0.40`

Final settings used for segment building: `noise_threshold=-50.0 dB`, `min_duration=0.100s`, `pad_sec=0.400s`.

### Edge cases

- **Target length ≥ original duration:** Output is a copy of the input (no detection).
- **No silences:** Every threshold probe resolves to the full duration, so the planner falls back to `-35.0 dB` with `0.060s` padding and returns the full file as best effort.
- **Padding search cannot expand safely:** padding stays at `0.060s`.
- **A threshold or padding probe is invalid:** that branch is treated as overshoot during search.

## Shared flow across modes

- Both target and non-target paths now use the same segment-builder implementation.
- The mode difference is how `pad_sec` is selected and what detection parameters are used:
  - Both modes now use the same shared edge-normalization helper (`prepare_silence_intervals_with_edges`) to apply edge replacement/trimming.
  - Non-target mode: fixed `noise_threshold`, `min_duration`, and `pad_sec` (`NON_TARGET_PAD_SEC`) with the shared edge helper applied before padding.
  - Target mode: fixed-parameter threshold search + padding search, with `min_duration=0.100s`, `base_padding=0.060s`, and the shared edge helper applied before each candidate length evaluation. Because final segment building still rejects silences `<= 2 * pad_sec`, the practical removable-silence floor stays around `0.120s`.

Implementation: `binary_search_threshold(...)` and `binary_search_padding(...)` live in `packages/sr_trim_plan/api.py`, alongside trim-plan assembly. The legacy `sr_threshold_selection` package remains for compatibility, but it is no longer the live target-mode planner.

## Final video output

The final encode applies the trim plan and makes the no-overlay video. The pipeline adds no title banner, no logo, and no subtitle track. The encode writes the title into the video metadata only.
