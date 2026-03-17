# Silence-removal algorithm

This document describes how silence is detected and how the trimmed output length is controlled. When a target length is set, a single detection pass and padding-only tuning are used.

## Basics

- **Silence detection** uses FFmpeg’s `silencedetect` filter: `silencedetect=n={noise_threshold}dB:d={min_duration}`.
- **noise_threshold (dB):** Must be negative. Audio below this level is considered silence. **Higher** (e.g. -20) = more is treated as silence = **shorter** output. **Lower** (e.g. -50) = only very quiet parts = **longer** output.
- **min_duration (s):** Minimum length of a quiet stretch to count as silence. **Lower** (e.g. 0.2) = short pauses removed = **shorter** output. **Higher** (e.g. 2.0) = only long gaps = **longer** output.
- **Padding:** For each detected silence we keep `pad_sec` at the end of the speech before and at the start of the speech after. **More padding** = **longer** output.

Segments to keep are built from (silence_starts, silence_ends) and padding; the concatenation of those segments is the trimmed duration.

## When no target length is set

- `NOISE_THRESHOLD` and `MIN_DURATION` from config (or env) are used as-is.
- If `PAD` is set, it is used; otherwise no padding tuning is done.

## When target length is set (`--target-length`)

When a target length is set, this algorithm is used. When target is not set, behavior is unchanged (config `NOISE_THRESHOLD` / `MIN_DURATION` / `PAD`).

### Overview

Goal: **preserve as much silence as possible** while trying to get the output to **at or under** the target length **without ever truncating content**.

We do this in two phases:

1. **Threshold sweep (conservative → aggressive):** start at **-60 dB** and increase the threshold until trimming can reach the target (with `pad=0`). This ensures we pick the *least aggressive* threshold that can meet the target, preserving silence.
2. **Padding tuning:** once we’ve found a threshold that can meet the target, increase uniform padding to get as close as possible to the target **without exceeding it**.

Min silence duration is fixed at **0.01s** in target mode.

### Steps

1. **Detect in passes** using `silencedetect=n={threshold}dB:d=0.01` for thresholds in `TARGET_NOISE_THRESHOLDS_DB` (starting at -60 dB).

2. **Base length at pad=0:** for each pass, compute:
   - `base_length = calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)`

3. **Pick the first threshold where `base_length <= target`:**
   - This is the **least aggressive** pass that can meet the target.

4. **Padding:** compute the largest uniform padding that stays under the target:
   - `pad_sec = find_optimal_padding(silence_starts, silence_ends, duration_sec, target_length)`
   - This guarantees the padded result remains **<= target**.

5. **Segments:** build segments from the chosen `(silence_starts, silence_ends)` and `pad_sec`. Silences with **duration ≤ 2 × pad_sec** are treated as non-silence (skipped), so very short gaps are merged with adjacent speech.

6. **No truncation:** if even the most aggressive threshold still results in output **> target**, we keep the output as-is (over target) rather than cutting content.

### Edge cases

- **Target length ≥ original duration:** Output is a copy of the input (no detection).
- **No silences:** Base length = full duration; `find_optimal_padding` returns 0; output is the full file.
- **Base length still > target even at the most aggressive threshold:** padding is forced to 0, and the output may remain above target (no truncation is applied).

Implementation: `choose_threshold_and_padding_for_target` and `find_optimal_padding` in `src/silence/detector.py`; target-length path in `trim_single_video` in `src/trim.py`.
