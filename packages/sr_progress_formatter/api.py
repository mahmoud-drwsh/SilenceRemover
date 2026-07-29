"""Progress formatting API for FFmpeg encode progress display.

Pure algorithm package - no FFmpeg dependencies, operates on pre-computed metrics.
Handles terminal formatting with throttled file size updates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProgressMetrics:
    """Raw progress data from FFmpeg encode.
    
    Attributes:
        percent: Completion percentage (0-100)
        encoded_seconds: Seconds of video FFmpeg has encoded so far
        wall_start_time: time.monotonic() value when encode started
    """
    percent: int
    encoded_seconds: float
    wall_start_time: float


class ProgressFormatter(Protocol):
    """Protocol for progress formatters."""
    
    def format_and_print(
        self,
        metrics: ProgressMetrics,
        file_size_bytes: int | None,
    ) -> None:
        """Format metrics and print progress line to terminal.
        
        Args:
            metrics: Current progress metrics from FFmpeg
            file_size_bytes: Current output file size in bytes, or None if unavailable
        """
        ...


class DefaultProgressFormatter:
    """Default terminal progress formatter with throttled file size display.
    
    Formats progress as: "Progress: 45% | 12.3s wall | 8.9s encoded | 0.72x | 156.42 MiB"
    
    File size updates are throttled to avoid excessive disk I/O during fast encodes.
    """
    
    def __init__(
        self,
        throttle_size_check_seconds: float = 1.0,
    ):
        """Initialize formatter with throttling configuration.
        
        Args:
            throttle_size_check_seconds: Minimum seconds between file size updates (default: 1.0)
        """
        self._throttle_seconds = throttle_size_check_seconds
        self._last_size_check_time: float = 0.0
        self._cached_size_mb: float | None = None
    
    def format_and_print(
        self,
        metrics: ProgressMetrics,
        file_size_bytes: int | None,
    ) -> None:
        """Format and print progress line with throttled file size updates.
        
        Calculates wall elapsed time and encoding speed internally.
        File size is only updated when throttle interval has passed.
        Output is printed to stdout with \r carriage return for in-place updates.
        
        Args:
            metrics: Current progress metrics from FFmpeg
            file_size_bytes: Current output file size in bytes, or None if unavailable
        """
        # Calculate timing metrics
        wall_elapsed = time.monotonic() - metrics.wall_start_time
        speed = metrics.encoded_seconds / max(wall_elapsed, 1e-6)
        
        # Throttle file size checks (update cached value only at interval)
        if file_size_bytes is not None:
            current_time = time.monotonic()
            if current_time - self._last_size_check_time >= self._throttle_seconds:
                self._cached_size_mb = file_size_bytes / 1048576
                self._last_size_check_time = current_time
        
        # Format size string
        if self._cached_size_mb is not None:
            size_str = f"{self._cached_size_mb:.2f} MiB"
        else:
            size_str = "n/a"
        
        # Build and print progress line
        line = (
            f"\rProgress: {metrics.percent}% | "
            f"{wall_elapsed:.1f}s wall | "
            f"{metrics.encoded_seconds:.1f}s encoded | "
            f"{speed:.2f}x | "
            f"{size_str}"
        )
        
        print(line, end="", flush=True)
