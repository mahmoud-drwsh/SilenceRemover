"""Video filtering utilities for pre-processing pipeline."""

from pathlib import Path
import subprocess


def get_video_duration(video_path: Path) -> float | None:
    """Get video duration in seconds using ffprobe.
    
    Args:
        video_path: Path to video file
        
    Returns:
        Duration in seconds, or None if failed
    """
    try:
result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        duration = float(result.stdout.strip())
        return duration
    except Exception:
        return None


def filter_short_videos(
    videos: list[Path],
    input_dir: Path,
    min_duration_sec: float = 10.0,
    *,
    temp_dir: Path | None = None,
    total_phases: int = 6,
) -> tuple[list[Path], list[Path]]:
    """Filter out videos shorter than min_duration_sec.
    
    Args:
        videos: List of video paths to check
        input_dir: Input directory (for creating ignored/ subfolder)
        min_duration_sec: Minimum duration in seconds (default: 10.0)
        temp_dir: Temp directory (for checking completed/ markers to skip ffprobe)
        total_phases: Total phases count (for progress display)
        
    Returns:
        (kept_videos, ignored_videos) tuple
        
    Behavior:
        - Creates input/ignored/ at startup if doesn't exist
        - For each video:
            - Check if completed marker exists (temp/completed/{basename}.txt)
            - If completed: skip ffprobe, keep video (fast path)
            - If not completed: ffprobe duration check
            - If duration < min_duration_sec:
                - Move file to input/ignored/
                - Show: [0/6] [15/276] filename.mp4 (8.2s) → ignored/
            - Else:
                - Keep in input/
                - Progress line updates silently
        - Ignores files already in ignored/ subfolder
        - Print summary at end
    """
    # Create ignored folder at startup
    ignored_dir = input_dir / 'ignored'
    ignored_dir.mkdir(exist_ok=True)
    
    # Filter out videos already in ignored/ folder
    videos_to_check = [v for v in videos if 'ignored' not in v.parts]
    already_ignored = [v for v in videos if 'ignored' in v.parts]
    
    kept_videos: list[Path] = []
    ignored_videos: list[Path] = list(already_ignored)  # Keep track of existing ignored
    total_videos = len(videos_to_check)
    
    if total_videos == 0:
        return kept_videos, ignored_videos
    
    # Check for completed markers directory
    completed_dir = temp_dir / 'completed' if temp_dir else None
    
    for i, video_path in enumerate(videos_to_check, 1):
        # Show checking status on single line
        short_name = video_path.name[:40] + "..." if len(video_path.name) > 40 else video_path.name
        print(f"\r[0/{total_phases}] [{i}/{total_videos}] Checking: {short_name}\033[K", end='', flush=True)
        
        # Fast path: check if video was already processed (skip ffprobe)
        basename = video_path.stem
        if completed_dir and (completed_dir / f"{basename}.txt").exists():
            # Already processed, skip ffprobe and keep it
            print(f"\r[0/{total_phases}] [{i}/{total_videos}] {short_name} \033[90m✓ already processed\033[0m\033[K", end='', flush=True)
            if i == total_videos:
                print()  # New line at end
            kept_videos.append(video_path)
            continue
        
        duration = get_video_duration(video_path)
        
        if duration is None:
            # Failed to get duration, keep the video to be safe
            print(f"\r[0/{total_phases}] [{i}/{total_videos}] {short_name} (duration unknown, keeping)\033[K")
            kept_videos.append(video_path)
            continue
        
        if duration < min_duration_sec:
            # Too short - move to ignored folder
            dest_path = ignored_dir / video_path.name
            try:
                video_path.rename(dest_path)
                ignored_videos.append(dest_path)
                print(f"\r[0/{total_phases}] [{i}/{total_videos}] {short_name} ({duration:.1f}s) \033[90m→ ignored/\033[0m")
            except Exception as e:
                # If move fails, keep it and show error
                print(f"\r[0/{total_phases}] [{i}/{total_videos}] {short_name} ({duration:.1f}s) \033[91mmove failed: {e}\033[0m")
                kept_videos.append(video_path)
        else:
            # Long enough - keep it
            print(f"\r[0/{total_phases}] [{i}/{total_videos}] {short_name} ({duration:.1f}s)\033[K", end='', flush=True)
            if i == total_videos:
                print()  # New line at end
            kept_videos.append(video_path)
    
    return kept_videos, ignored_videos
