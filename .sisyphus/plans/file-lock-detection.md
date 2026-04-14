# Implementation Plan: File Lock Detection for Video Discovery

## Problem
Pipeline processes videos while they're still being recorded, leading to incomplete transcription.

## Solution
Add a simple file stability check in `collect_video_files()` to skip files that are still being written to.

## Implementation Details

### Location: `src/core/cli.py`

### Changes Required:

#### 1. Add `is_file_stable()` helper function (before `collect_video_files()`)

```python
def is_file_stable(file_path: Path, check_delay: float = 1.0) -> bool:
    """Check if file is stable (not being written to).
    
    Compares file size before and after a short delay.
    If size changes, file is still being written to.
    
    Args:
        file_path: Path to check
        check_delay: Seconds to wait between checks (default 1.0)
    
    Returns:
        True if file size hasn't changed (stable), False if still being written
    """
    try:
        # Get initial size
        initial_size = file_path.stat().st_size
        
        # Wait a bit
        time.sleep(check_delay)
        
        # Get size again
        final_size = file_path.stat().st_size
        
        # If size changed, file is still being written
        return initial_size == final_size
    except (OSError, IOError):
        # If we can't stat the file, assume it's not stable
        return False
```

#### 2. Modify `collect_video_files()` to filter out unstable files

**Current code (lines 47-49):**
```python
def collect_video_files(input_dir: Path) -> list[Path]:
    """Collect supported video files from a directory."""
    return sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
```

**New code:**
```python
def collect_video_files(input_dir: Path) -> list[Path]:
    """Collect supported video files from a directory.
    
    Filters out files that are still being written to (e.g., being recorded).
    """
    video_files = []
    for p in input_dir.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
            if is_file_stable(p, check_delay=1.0):
                video_files.append(p)
            else:
                print(f"Skipping file still being written: {p.name}")
    return sorted(video_files)
```

#### 3. Add `time` import at top of file

Add to existing imports:
```python
import time
```

## Files to Modify:
- `src/core/cli.py` - Add stability check function and integrate into file collection

## Verification Steps:
1. Syntax check: `python -m py_compile src/core/cli.py`
2. Test with a stable video file - should be collected
3. Test with a file being written (e.g., recording in progress) - should be skipped

## Acceptance Criteria:
- [ ] Pipeline skips files that are still growing/changing
- [ ] No error when encountering locked files
- [ ] Message printed when skipping unstable files
- [ ] Existing behavior preserved for stable files

## Dependencies: None
## Estimated Effort: 30 minutes
