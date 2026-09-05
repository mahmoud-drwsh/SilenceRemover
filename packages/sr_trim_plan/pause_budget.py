"""Duration budgeting over fixed quiet intervals, independent of their detector.

Defaults are conservative editorial choices, not universal perceptual thresholds.
See docs/research/natural-pause-budget.md. All allocation uses integer microseconds.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

_SCALE = 1_000_000
NATURAL_PAUSE_POLICY_VERSION = "natural-pause-budget-v1"


@dataclass(frozen=True)
class PausePolicy:
    min_gap_sec: float = 0.6
    max_gap_sec: float = 1.2
    edge_keep_sec: float = 0.2
    render_margin_sec: float = 0.5

    def __post_init__(self) -> None:
        values = (self.min_gap_sec, self.max_gap_sec, self.edge_keep_sec, self.render_margin_sec)
        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError("Pause policy values must be finite and nonnegative")
        if self.min_gap_sec <= 0 or self.max_gap_sec < self.min_gap_sec:
            raise ValueError("Require 0 < min_gap_sec <= max_gap_sec")
        if self.render_margin_sec <= 0:
            raise ValueError("An exclusive duration target requires positive render margin")


class TargetDurationUnreachable(ValueError):
    """Do not publish an over-target result or silently delete protected content."""

    def __init__(self, minimum_sec: float, budget_sec: float) -> None:
        self.minimum_sec = minimum_sec
        self.budget_sec = budget_sec
        super().__init__(
            f"Target unreachable with protected pauses: shortest permitted timeline "
            f"is {minimum_sec:.3f}s; planning budget is {budget_sec:.3f}s. "
            "Split or manually edit this recording; speech was not truncated."
        )


@dataclass(frozen=True)
class PauseBudget:
    segments: list[tuple[float, float]]
    retained_gaps_sec: list[float]
    resulting_length_sec: float
    minimum_length_sec: float
    budget_sec: float


def allocate_pause_budget(
    duration_sec: float,
    silence_starts: list[float],
    silence_ends: list[float],
    target_sec: float,
    policy: PausePolicy = PausePolicy(),
) -> PauseBudget:
    """Keep all material outside validated quiet intervals and bound each pause.

    Preserve gaps shorter than the floor. Cap long gaps, then distribute only the
    remaining required reduction in proportion to each gap's available slack.
    Retain half the allocated internal pause at each speech boundary. Edge
    silence retains only its speech-adjacent portion. No speedup or end truncation.
    """
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise ValueError("Duration must be finite and positive")
    if not math.isfinite(target_sec) or target_sec <= policy.render_margin_sec:
        raise ValueError("Target must be finite and greater than render margin")
    if len(silence_starts) != len(silence_ends):
        raise ValueError("Silence interval lists must have equal lengths")
    duration = round(duration_sec * _SCALE)
    # Never round the exclusive target budget upward.
    budget = math.floor((target_sec - policy.render_margin_sec) * _SCALE)
    intervals: list[tuple[int, int]] = []
    previous_end = 0
    for start, end in zip(silence_starts, silence_ends):
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Silence boundaries must be finite")
        if start < 0 or end > duration_sec + 1e-6 or end <= start:
            raise ValueError("Silence interval is outside the input timeline")
        a, b = round(start * _SCALE), min(duration, round(end * _SCALE))
        if a < previous_end or b <= a:
            raise ValueError("Silence intervals must be ordered and non-overlapping")
        # Adjacent intervals are one pause, not two independent budgets.
        if intervals and a == previous_end:
            intervals[-1] = (intervals[-1][0], b)
        else:
            intervals.append((a, b))
        previous_end = b
    if intervals == [(0, duration)]:
        raise ValueError("Source is entirely detected silence; manual review required")

    floor = round(policy.min_gap_sec * _SCALE)
    cap = round(policy.max_gap_sec * _SCALE)
    edge = round(policy.edge_keep_sec * _SCALE)
    lower, upper = [], []
    for a, b in intervals:
        gap = b - a
        if a == 0 or b == duration:
            lo = hi = min(gap, edge)
        else:
            lo, hi = min(gap, floor), min(gap, cap)
        lower.append(lo)
        upper.append(hi)
    protected = duration - sum(b - a for a, b in intervals)
    minimum = protected + sum(lower)
    if minimum > budget:
        raise TargetDurationUnreachable(minimum / _SCALE, budget / _SCALE)
    slack = sum(hi - lo for lo, hi in zip(lower, upper))
    allowance = min(slack, budget - minimum)
    retained = [lo + ((hi - lo) * allowance // slack if slack else 0)
                for lo, hi in zip(lower, upper)]
    # Integer division can leave < N microseconds; restore them deterministically.
    remainder = minimum + allowance - protected - sum(retained)
    for i in range(len(retained)):
        if remainder and retained[i] < upper[i]:
            retained[i] += 1
            remainder -= 1

    cuts: list[tuple[int, int]] = []
    for (a, b), keep in zip(intervals, retained):
        if keep >= b - a:
            continue
        if a == 0:
            cuts.append((a, b - keep))
        elif b == duration:
            cuts.append((a + keep, b))
        else:
            cuts.append((a + keep // 2, b - (keep - keep // 2)))
    segments = []
    cursor = 0
    for a, b in cuts:
        if a > cursor:
            segments.append((cursor / _SCALE, a / _SCALE))
        cursor = b
    if cursor < duration:
        segments.append((cursor / _SCALE, duration / _SCALE))
    return PauseBudget(
        segments=segments,
        retained_gaps_sec=[value / _SCALE for value in retained],
        resulting_length_sec=(protected + sum(retained)) / _SCALE,
        minimum_length_sec=minimum / _SCALE,
        budget_sec=budget / _SCALE,
    )
