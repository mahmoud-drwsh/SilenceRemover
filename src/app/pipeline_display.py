"""Rich-based progress display for SilenceRemover pipeline with graceful fallback."""

from __future__ import annotations

import os
import sys
from typing import Literal


class _FallbackProgress:
    """Plain-text fallback when Rich is unavailable or disabled."""

    def __init__(self) -> None:
        self._current_line = ""

    def update(self, line: str) -> None:
        """Update the current line using ANSI escape codes."""
        self._current_line = line
        print(f"\r{line}\033[K", end="", flush=True)

    def newline(self) -> None:
        """Move to new line."""
        print()

    def print(self, text: str) -> None:
        """Print text with newline."""
        print(text)


class PipelineProgress:
    """Rich-based progress display for 8-phase pipeline with graceful fallback."""

    def __init__(self, use_rich: bool | None = None) -> None:
        """Initialize progress display with optional Rich integration.

        Args:
            use_rich: Force Rich usage (True), disable (False), or auto-detect (None)
        """
        self._rich_available = False
        self._progress = None
        self._console = None
        self._task_id: int | None = None
        self._fallback = _FallbackProgress()

        # Auto-detect if not specified
        if use_rich is None:
            use_rich = self._should_use_rich()

        if use_rich:
            try:
                from rich.console import Console
                from rich.progress import (
                    MofNCompleteColumn,
                    Progress,
                    SpinnerColumn,
                    TextColumn,
                )

                self._console = Console(force_terminal=True)
                self._progress = Progress(
                    MofNCompleteColumn(),
                    TextColumn(" "),
                    SpinnerColumn(
                        spinner_name="dots",
                        finished_text=" ",
                    ),
                    TextColumn(" "),
                    TextColumn("[bold]{task.description}[/bold]"),
                    TextColumn(" [dim]-[/dim] "),
                    TextColumn("[yellow]{task.fields[filename]}[/yellow]"),
                    TextColumn(" "),
                    TextColumn("[{task.fields[status_style]}]{task.fields[status_symbol]}[/]"),
                    TextColumn("[dim]{task.fields[message]}[/dim]"),
                    console=self._console,
                    refresh_per_second=10,
                    transient=False,
                )
                self._rich_available = True
            except ImportError:
                pass

    def _should_use_rich(self) -> bool:
        """Determine if Rich should be used based on environment."""
        if os.environ.get("SILENCE_REMOVER_NO_RICH"):
            return False
        if not sys.stdout.isatty():
            return False
        if os.environ.get("CI"):
            return False
        return True

    def __enter__(self) -> PipelineProgress:
        """Context manager entry."""
        if self._progress:
            self._progress.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.stop()

    def start_pipeline(self, total_phases: int, total_videos: int) -> None:
        """Initialize progress tracking for pipeline start."""
        self._total_phases = total_phases
        self._total_videos = total_videos
        if self._progress:
            self._task_id = self._progress.add_task(
                "Starting",
                filename="",
                status_symbol="⋯",
                status_style="blue",
                message="",
                total=total_videos,
            )

    def start_phase(
        self,
        phase_index: int,
        phase_name: str,
        video_name: str,
        video_index: int = 1,
    ) -> None:
        """Mark phase start with spinner animation."""
        short_name = video_name[:40] + "..." if len(video_name) > 40 else video_name

        if self._rich_available and self._task_id is not None:
            description = f"[{phase_index}/{self._total_phases}] {phase_name}"
            self._progress.update(
                self._task_id,
                description=description,
                filename=short_name,
                status_symbol="⋯",
                status_style="bold blue",
                message="",
                completed=video_index - 1,
            )
        else:
            line = f"[{phase_index}/{self._total_phases}] {phase_name} - {short_name}"
            self._fallback.update(line)

    def update_status(
        self,
        status: Literal["done", "skip", "error"],
        message: str = "",
    ) -> None:
        """Update phase status with color coding.

        Args:
            status: One of done (green), skip (yellow), error (red)
            message: Optional status message
        """
        status_map = {
            "done": ("✓", "bold green"),
            "skip": ("⊘", "bold yellow"),
            "error": ("✗", "bold red"),
        }
        symbol, style = status_map.get(status, ("?", "white"))

        if self._rich_available and self._task_id is not None:
            self._progress.update(
                self._task_id,
                status_symbol=symbol,
                status_style=style,
                message=message,
            )
        else:
            # Fallback: add status to current line and newline
            short_msg = f" ({message})" if message else ""
            self._fallback.update(f"{self._fallback._current_line} {symbol}{short_msg}")
            self._fallback.newline()

    def stop(self) -> None:
        """Cleanup and finalize display."""
        if self._progress:
            self._progress.stop()

    def print_summary(
        self,
        success: int,
        skipped: int,
        failed: int,
    ) -> None:
        """Print final statistics with colors."""
        if self._rich_available:
            from rich.text import Text

            summary = Text()
            summary.append("✓ Pipeline complete: ", style="bold")
            summary.append(f"{success} done", style="bold green")
            summary.append(", ", style="dim")
            summary.append(f"{skipped} skipped", style="bold yellow")
            summary.append(", ", style="dim")
            summary.append(f"{failed} failed", style="bold red")
            self._console.print(summary)
        else:
            print(f"✓ Pipeline complete: {success} done, {skipped} skipped, {failed} failed")
