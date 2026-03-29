"""Internal: Parse FFmpeg silencedetect filter output."""

from __future__ import annotations

import re


def _parse_silence_output(result: str) -> tuple[list[float], list[float]]:
    """Parse silencedetect output into silence start/end lists."""
    silence_starts = [float(x) for x in re.findall(r"silence_start: (-?\d+\.?\d*)", result)]
    silence_ends = [float(x) for x in re.findall(r"silence_end: (\d+\.?\d*)", result)]
    return silence_starts, silence_ends


def _parse_dual_silence_output(stderr: str) -> tuple[tuple[list[float], list[float]], tuple[list[float], list[float]], bool]:
    """Split stderr from a chained dual silencedetect filter into (primary, edge) interval lists.

    FFmpeg tags each filter instance with ``[silencedetect @ 0x...]``; we bucket by pointer in
    order of first appearance (matches filter chain order: primary then edge).

    Returns ``(primary, edge, ok)``. If fewer than two distinct filter pointers appear in the log
    (e.g. one filter emitted no lines), ``ok`` is False and callers should fall back to two
    separate ``_detect_raw`` runs.
    """
    ptr_order: list[str] = []
    seen: set[str] = set()
    for line in stderr.splitlines():
        m = re.search(r"\[silencedetect @ (0x[0-9a-fA-F]+)\]", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ptr_order.append(m.group(1))

    if len(ptr_order) < 2:
        return ([], []), ([], []), False

    ptr_to_bucket = {p: i for i, p in enumerate(ptr_order[:2])}

    starts: list[list[float]] = [[], []]
    ends: list[list[float]] = [[], []]
    start_re = re.compile(r"silence_start: (-?\d+\.?\d*)")
    end_re = re.compile(r"silence_end: (\d+\.?\d*)")
    for line in stderr.splitlines():
        m = re.search(r"\[silencedetect @ (0x[0-9a-fA-F]+)\]", line)
        if not m:
            continue
        bi = ptr_to_bucket.get(m.group(1))
        if bi is None:
            continue
        sm = start_re.search(line)
        if sm:
            starts[bi].append(float(sm.group(1)))
        em = end_re.search(line)
        if em:
            ends[bi].append(float(em.group(1)))

    return (starts[0], ends[0]), (starts[1], ends[1]), True
