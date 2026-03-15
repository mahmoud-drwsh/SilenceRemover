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

1. **Detect once** with fixed **-55 dB** and **0.01 s** min_duration (`SIMPLE_DB`, `SIMPLE_MIN_DURATION` in `src/config.py`). No sweep over threshold or min_duration.

2. **Base length:** Compute the resulting length with `pad_sec = 0` using `calculate_resulting_length(silence_starts, silence_ends, duration_sec, 0.0)`.

3. **Padding:**
   - If base length **≥ target:** use `pad_sec = 0` (padding only lengthens; target cannot be reached). A message is printed.
   - If base length **< target:** call `find_optimal_padding` to get the largest uniform `pad_sec` that keeps the final length just below the target.

4. **Segments:** Build segments from the same `(silence_starts, silence_ends)` and chosen `pad_sec`. The same rule applies: silences with **duration ≤ 2 × pad_sec** are treated as non-silence (skipped), so very short gaps are merged with adjacent speech. Only longer silences are trimmed with padding before/after.

### Edge cases

- **Target length ≥ original duration:** Output is a copy of the input (no detection).
- **No silences:** Base length = full duration; `find_optimal_padding` returns 0; output is the full file.
- **Base length already ≥ target:** Use `pad_sec = 0`; output may be longer than target.

Implementation: `detect_silences_simple` and `find_optimal_padding` in `src/silence_utils.py`; target-length path in `trim_single_video` in `src/trim.py`.
