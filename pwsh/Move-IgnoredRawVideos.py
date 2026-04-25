from __future__ import annotations

import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".webm",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ogv",
    ".ts",
    ".m2ts",
}

SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<value>-?\d+(?:\.\d+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<value>-?\d+(?:\.\d+)?)")
ANSI_CLEAR_TO_END_OF_LINE = "\x1b[K"
IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value  # type: ignore[arg-type]
    OPEN_EXISTING = 3
    GENERIC_READ = 0x80000000
    ERROR_FILE_NOT_FOUND = 2
    ERROR_PATH_NOT_FOUND = 3
    ERROR_SHARING_VIOLATION = 32
    ERROR_LOCK_VIOLATION = 33
else:  # pragma: no cover - non-Windows branch
    _CreateFileW = None
    _CloseHandle = None
    INVALID_HANDLE_VALUE = None
    OPEN_EXISTING = None
    GENERIC_READ = None
    ERROR_FILE_NOT_FOUND = None
    ERROR_PATH_NOT_FOUND = None
    ERROR_SHARING_VIOLATION = None
    ERROR_LOCK_VIOLATION = None


@dataclass(frozen=True)
class ScanSummary:
    label: str
    scanned: int
    locked: int
    completed_skipped: int
    moved: int


class LiveSkipStatus:
    def __init__(self, stream: object) -> None:
        self.stream = stream
        self._is_tty = bool(getattr(stream, "isatty", lambda: False)())
        self._open = False

    def close(self) -> None:
        if not self._open:
            return
        print(file=self.stream, flush=True)
        self._open = False

    def show(
        self,
        label: str,
        file_index: int,
        total_files: int,
        name: str,
        reason: str,
        skip_count: int,
    ) -> None:
        if self._is_tty:
            message = (
                f"[{label}] Skip {file_index}/{total_files}: "
                f"{name} ({reason}) | skipped {skip_count}"
            )
            self.stream.write(f"\r{message}{ANSI_CLEAR_TO_END_OF_LINE}")
            self.stream.flush()
            self._open = True
            return
        print(f"  skip: {name} ({reason})", file=self.stream, flush=True)


LIVE_SKIP_STATUS = LiveSkipStatus(sys.stdout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Raw preflight scanner for SilenceRemover.")
    parser.add_argument(
        "--videos-root",
        default=str(Path.home() / "Videos"),
        help="Root directory containing raw/ and Vertical/raw/ directories.",
    )
    parser.add_argument(
        "--short-duration-seconds",
        type=float,
        default=30.0,
        help="Move unlocked videos shorter than this many seconds to ignored/.",
    )
    parser.add_argument(
        "--silence-threshold-db",
        type=float,
        default=-50.0,
        help="FFmpeg silencedetect threshold in dB.",
    )
    parser.add_argument(
        "--silence-min-duration-seconds",
        type=float,
        default=0.1,
        help="Minimum silence duration for FFmpeg silencedetect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print move decisions without changing files.",
    )
    parser.add_argument(
        "--targets",
        choices=("horizontal", "vertical", "both"),
        default="both",
        help="Which raw directories to scan. Defaults to both.",
    )
    return parser.parse_args()


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool '{name}' was not found on PATH.")


def is_file_locked(path: Path) -> bool:
    if not (IS_WINDOWS and _CreateFileW):
        return False

    handle = _CreateFileW(
        str(path),
        GENERIC_READ,
        0,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle != INVALID_HANDLE_VALUE:
        _CloseHandle(handle)
        return False

    err = ctypes.get_last_error()
    if err in (ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND):
        return False
    return err in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION)


def get_media_duration_seconds(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    try:
        return float(raw)
    except ValueError:
        return None


def has_audio_stream(path: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def is_fully_silent_video(
    path: Path,
    duration_seconds: float,
    silence_threshold_db: float,
    silence_min_duration_seconds: float,
) -> bool:
    if duration_seconds <= 0:
        return False

    if not has_audio_stream(path):
        return False

    filter_text = (
        f"silencedetect=n={silence_threshold_db}dB:d={silence_min_duration_seconds}"
    )
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-v",
            "info",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            filter_text,
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return False

    start_matches = SILENCE_START_RE.findall(result.stderr)
    end_matches = SILENCE_END_RE.findall(result.stderr)
    if not start_matches or not end_matches:
        return False

    if len(start_matches) != 1 or len(end_matches) != 1:
        return False

    try:
        first_start = float(start_matches[0])
        last_end = float(end_matches[-1])
    except ValueError:
        return False

    tolerance = max(0.15, min(0.5, duration_seconds * 0.01))
    return first_start <= tolerance and (duration_seconds - last_end) <= tolerance


def get_unique_ignored_destination(file_path: Path, ignored_dir: Path) -> Path:
    destination = ignored_dir / file_path.name
    if not destination.exists():
        return destination

    for index in range(1, 1000):
        candidate = ignored_dir / f"{file_path.stem}__ignored_{index}{file_path.suffix}"
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find a unique ignored destination for '{file_path}'.")


def move_to_ignored(file_path: Path, ignored_dir: Path, reason: str, dry_run: bool) -> None:
    LIVE_SKIP_STATUS.close()

    if dry_run:
        destination = ignored_dir / file_path.name
        print(
            f"  [dry-run] move '{file_path.name}' -> '{destination}' ({reason})",
            flush=True,
        )
        return

    ignored_dir.mkdir(parents=True, exist_ok=True)
    destination = get_unique_ignored_destination(file_path, ignored_dir)
    shutil.move(str(file_path), str(destination))
    print(f"  moved '{file_path.name}' -> '{destination}' ({reason})", flush=True)


def get_completed_marker_path(raw_path: Path, file_path: Path) -> Path:
    root_dir = raw_path.parent
    return root_dir / "output" / "temp" / "completed" / f"{file_path.stem}.txt"


def iter_video_files(raw_path: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in raw_path.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ),
        key=lambda path: path.name,
    )


def invoke_raw_preflight_scan(
    *,
    label: str,
    raw_path: Path,
    short_duration_seconds: float,
    silence_threshold_db: float,
    silence_min_duration_seconds: float,
    dry_run: bool,
) -> ScanSummary:
    LIVE_SKIP_STATUS.close()
    print(f"\n=== {label} raw preflight ===", flush=True)

    if not raw_path.exists():
        print(f"  raw directory not found: {raw_path}", flush=True)
        return ScanSummary(label=label, scanned=0, locked=0, completed_skipped=0, moved=0)

    video_files = iter_video_files(raw_path)
    if not video_files:
        print("  no supported video files found", flush=True)
        return ScanSummary(label=label, scanned=0, locked=0, completed_skipped=0, moved=0)

    ignored_dir = raw_path / "ignored"
    locked_count = 0
    moved_count = 0
    completed_skip_count = 0

    for index, file_path in enumerate(video_files, start=1):
        completed_marker_path = get_completed_marker_path(raw_path, file_path)
        if completed_marker_path.exists():
            completed_skip_count += 1
            LIVE_SKIP_STATUS.show(
                label,
                index,
                len(video_files),
                file_path.name,
                "completed marker exists",
                locked_count + completed_skip_count,
            )
            continue

        if is_file_locked(file_path):
            locked_count += 1
            LIVE_SKIP_STATUS.show(
                label,
                index,
                len(video_files),
                file_path.name,
                "locked file",
                locked_count + completed_skip_count,
            )
            continue

        duration = get_media_duration_seconds(file_path)
        if duration is None or duration <= 0:
            continue

        if duration < short_duration_seconds:
            move_to_ignored(
                file_path,
                ignored_dir,
                f"too short ({duration:.2f}s < {short_duration_seconds:.2f}s)",
                dry_run,
            )
            moved_count += 1
            continue

        if is_fully_silent_video(
            file_path,
            duration,
            silence_threshold_db,
            silence_min_duration_seconds,
        ):
            move_to_ignored(
                file_path,
                ignored_dir,
                f"fully silent ({duration:.2f}s)",
                dry_run,
            )
            moved_count += 1
            continue

        LIVE_SKIP_STATUS.close()
        print(f"  keeping '{file_path.name}' ({duration:.2f}s)", flush=True)

    LIVE_SKIP_STATUS.close()
    return ScanSummary(
        label=label,
        scanned=len(video_files),
        locked=locked_count,
        completed_skipped=completed_skip_count,
        moved=moved_count,
    )


def main() -> int:
    args = parse_args()

    require_tool("ffmpeg")
    require_tool("ffprobe")

    videos_root = Path(args.videos_root)
    scan_specs: list[tuple[str, Path]] = []
    if args.targets in ("horizontal", "both"):
        scan_specs.append(("Horizontal", videos_root / "raw"))
    if args.targets in ("vertical", "both"):
        scan_specs.append(("Vertical", videos_root / "Vertical" / "raw"))

    summaries = [
        invoke_raw_preflight_scan(
            label=label,
            raw_path=raw_path,
            short_duration_seconds=args.short_duration_seconds,
            silence_threshold_db=args.silence_threshold_db,
            silence_min_duration_seconds=args.silence_min_duration_seconds,
            dry_run=args.dry_run,
        )
        for label, raw_path in scan_specs
    ]

    LIVE_SKIP_STATUS.close()
    print("\n=== Raw preflight summary ===", flush=True)
    for summary in summaries:
        print(
            "  {0}: scanned {1}, locked {2}, completed-skip {3}, moved {4}".format(
                summary.label,
                summary.scanned,
                summary.locked,
                summary.completed_skipped,
                summary.moved,
            ),
            flush=True,
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LIVE_SKIP_STATUS.close()
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1)
