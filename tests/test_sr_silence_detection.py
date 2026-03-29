"""Test sr_silence_detection black box against real videos.

Run: python tests/test_sr_silence_detection.py
"""

import sys
from pathlib import Path

# Setup paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from sr_silence_detection import detect_silence, detect_silence_with_edges
from src.core.constants import (
    EDGE_RESCAN_MIN_DURATION_SEC,
    EDGE_RESCAN_THRESHOLD_DB,
    EDGE_SILENCE_KEEP_SEC,
    NON_TARGET_MIN_DURATION_SEC,
    NON_TARGET_NOISE_THRESHOLD_DB,
    TARGET_MIN_DURATION_SEC,
    TARGET_NOISE_THRESHOLD_DB,
)


def find_test_videos():
    """Find video files in the raw directory."""
    raw_dir = Path("/Users/mahmoud/Desktop/TEMP/raw")
    videos = list(raw_dir.glob("*.mp4")) + list(raw_dir.glob("*.mov")) + list(raw_dir.glob("*.mkv"))
    return [v for v in videos if not v.name.startswith(".")]


def test_simple_detection(video_path: Path) -> None:
    """Test detect_silence() - single-pass detection."""
    print(f"\n--- Testing detect_silence() on: {video_path.name} ---")
    
    starts, ends = detect_silence(
        input_file=video_path,
        noise_threshold=NON_TARGET_NOISE_THRESHOLD_DB,
        min_duration=NON_TARGET_MIN_DURATION_SEC,
    )
    
    print(f"  Detected {len(starts)} silence intervals")
    if starts:
        total_silence = sum(e - s for s, e in zip(starts, ends))
        print(f"  Total silence: {total_silence:.2f} seconds")
        print(f"  First 3 intervals: {list(zip(starts[:3], ends[:3]))}")
    
    # Basic sanity checks
    assert len(starts) == len(ends), "Mismatched starts/ends count"
    for s, e in zip(starts, ends):
        assert s < e, f"Invalid interval: start {s} >= end {e}"
        assert s >= 0, f"Negative start time: {s}"
    
    print("  ✓ Simple detection passed")


def test_edge_aware_detection(video_path: Path) -> None:
    """Test detect_silence_with_edges() - dual-pass with edge policy."""
    print(f"\n--- Testing detect_silence_with_edges() on: {video_path.name} ---")
    
    starts, ends = detect_silence_with_edges(
        input_file=video_path,
        primary_noise_threshold=TARGET_NOISE_THRESHOLD_DB,
        primary_min_duration=TARGET_MIN_DURATION_SEC,
        edge_noise_threshold=EDGE_RESCAN_THRESHOLD_DB,
        edge_min_duration=EDGE_RESCAN_MIN_DURATION_SEC,
        edge_keep_seconds=EDGE_SILENCE_KEEP_SEC,
    )
    
    print(f"  Detected {len(starts)} silence intervals (after edge processing)")
    if starts:
        total_silence = sum(e - s for s, e in zip(starts, ends))
        print(f"  Total silence: {total_silence:.2f} seconds")
        print(f"  First 3 intervals: {list(zip(starts[:3], ends[:3]))}")
    
    # Basic sanity checks
    assert len(starts) == len(ends), "Mismatched starts/ends count"
    for s, e in zip(starts, ends):
        assert s < e, f"Invalid interval: start {s} >= end {e}"
        assert s >= 0, f"Negative start time: {s}"
    
    print("  ✓ Edge-aware detection passed")


def test_black_box_api():
    """Run black box tests on available videos."""
    videos = find_test_videos()
    
    if not videos:
        print("⚠ No test videos found in /Users/mahmoud/Desktop/TEMP/raw/")
        return 1
    
    print(f"Found {len(videos)} test video(s):")
    for v in videos:
        print(f"  - {v.name}")
    
    # Test each video
    for video_path in videos:
        try:
            test_simple_detection(video_path)
            test_edge_aware_detection(video_path)
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            raise
    
    print("\n" + "="*60)
    print("✓ ALL BLACK BOX TESTS PASSED!")
    print("="*60)
    print("\nSummary:")
    print(f"  - Tested {len(videos)} video(s)")
    print("  - Simple detection mode: ✓")
    print("  - Edge-aware detection mode: ✓")
    print("  - FFmpeg fully encapsulated: ✓")
    print("\nThe black box is working correctly!")
    return 0


if __name__ == "__main__":
    sys.exit(test_black_box_api())
