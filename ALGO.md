# Silence-removal algorithm

This document describes how silence is detected and how the trimmed output length is controlled. When a target length is set, the code sweeps thresholds (multiple detection passes) and then does padding-only tuning.

## Basics

- **Silence detection** uses FFmpeg’s `silencedetect` filter: `silencedetect=n={noise_threshold}dB:d={min_duration}`.
- **noise_threshold (dB):** Must be negative. Audio below this level is considered silence. **Higher** (e.g. -20) = more is treated as silence = **shorter** output. **Lower** (e.g. -50) = only very quiet parts = **longer** output.
- **min_duration (s):** Minimum length of a quiet stretch to count as silence. **Lower** (e.g. 0.2) = short pauses removed = **shorter** output. **Higher** (e.g. 2.0) = only long gaps = **longer** output.
- **Padding:** For each detected silence, segment-building keeps up to `pad_sec` seconds *before the silence ends* (i.e., it starts the next kept segment at `silence_end - pad_sec`). In addition, silences with **duration ≤ 2 × pad_sec** are treated as non-silence (skipped), merging adjacent speech across very short gaps. **More padding** = **longer** output.

Segments to keep are built from (silence_starts, silence_ends) and padding; the concatenation of those segments is the trimmed duration.

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

- `--noise-threshold` / `--min-duration` (if provided) are used; otherwise defaults from `src/constants.py` are used.
- `pad_sec` is currently always `DEFAULT_PAD_SEC` from `src/constants.py` (no CLI override).

## When target length is set (`--target-length`)

When a target length is set, this algorithm is used. When target is not set, noise/min-duration come from CLI overrides (if provided) or `src/constants.py` defaults; padding comes from `DEFAULT_PAD_SEC`.

### Overview

Goal: **preserve as much silence as possible** while trying to get the output to **at or under** the target length **without ever truncating content**.

We do this in two phases:

1. **Threshold sweep (conservative → aggressive):** start at **-60 dB** and increase the threshold until trimming can reach the target (with `pad=0`). This ensures we pick the *least aggressive* threshold that can meet the target, preserving silence.
2. **Padding tuning:** once we’ve found a threshold that can meet the target, increase uniform padding to get as close as possible to the target while staying **strictly under** it.

Min silence duration is fixed at **0.01s** in target mode.

### Steps

1. **Detect in passes** using `silencedetect=n={threshold}dB:d=0.01` for thresholds in `TARGET_NOISE_THRESHOLDS_DB` (starting at -60 dB).

2. **Base length at pad=0:** for each pass, compute:
   - `base_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)`

3. **Pick the first threshold where `base_length <= target`:**
   - This is the **least aggressive** pass that can meet the target.

4. **Padding:** compute the largest uniform padding that stays under the target:
   - `pad_sec = find_optimal_padding(silence_starts, silence_ends, duration_sec, target_length)`
   - This guarantees the padded result is **strictly under** the target (it may land slightly under). If `pad=0` already equals the target, padding stays at 0.

5. **Segments:** build segments from the chosen `(silence_starts, silence_ends)` and `pad_sec`. Silences with **duration ≤ 2 × pad_sec** are treated as non-silence (skipped), so very short gaps are merged with adjacent speech.

6. **No truncation:** if even the most aggressive threshold still results in output **> target**, we keep the output as-is (over target) rather than cutting content.

### Example C: Target-mode sweep + padding tuning (end-to-end)

Assume:

- Original duration = 120.0s
- Target length = 90.0s
- Threshold candidates = \[-60, -55, -50, -45, ...\] dB
- `min_duration=0.01s` in target mode

The sweep checks each threshold with `pad=0`:

- At **-60 dB**, base result is 98.0s → **too long** (98 > 90), continue.
- At **-55 dB**, base result is 92.0s → **too long**, continue.
- At **-50 dB**, base result is 88.0s → **meets target** (88 ≤ 90), choose **-50 dB**.

Then padding tuning tries to add uniform padding while staying strictly under 90.0s:

- `pad=0.00` → 88.0s
- `pad=0.20` → 89.4s (**< 90.0**, still under)
- `pad=0.25` → 90.2s (**≥ 90.0**, stop) ⇒ choose `pad=0.20`

Final settings used for segment building: `noise_threshold=-50dB`, `min_duration=0.01s`, `pad_sec=0.20s`.

### Edge cases

- **Target length ≥ original duration:** Output is a copy of the input (no detection).
- **No silences:** Base length = full duration; `find_optimal_padding` returns 0; output is the full file.
- **Base length still > target even at the most aggressive threshold:** padding is forced to 0, and the output may remain above target (no truncation is applied).

Implementation: `choose_threshold_and_padding_for_target` and `find_optimal_padding` in `src/silence/detector.py`; target-length path in `trim_single_video` in `src/trim.py`.
