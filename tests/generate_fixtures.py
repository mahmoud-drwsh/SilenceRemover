"""Generate test video fixtures for integration tests.

Uses FFmpeg to programmatically generate test videos with specific characteristics:
- Controlled duration, resolution, and format
- Audio with silence sections
- Varying audio levels
- No audio (for edge cases)

All videos are generated on-demand, no binary files stored in git.
"""

import subprocess
from pathlib import Path


def generate_test_video(
    output_path: Path,
    duration: float = 5.0,
    width: int = 1080,
    height: int = 1920,  # Vertical format
    fps: int = 30,
    audio: bool = True,
    silence_sections: list[tuple[float, float]] | None = None,
    audio_varying: bool = False,
) -> None:
    """Generate a test video using FFmpeg.
    
    Args:
        output_path: Where to save the video
        duration: Video duration in seconds
        width: Video width in pixels
        height: Video height in pixels
        fps: Frames per second
        audio: Whether to include audio
        silence_sections: List of (start, end) tuples for silence sections
        audio_varying: Whether to vary audio volume over time
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Video input: test pattern (color bars or solid color)
    video_input = [
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size={width}x{height}:rate={fps}",
    ]
    
    if audio:
        if silence_sections:
            # Create audio with silence sections using acomplex filter
            # Base audio: sine wave at 1000Hz
            audio_filters = []
            for start, end in silence_sections:
                audio_filters.append(f"volume=enable='between(t,{start},{end})':volume=0")
            
            if audio_varying:
                # Add volume variation (fade in/out)
                audio_filters.append("volume='if(lt(t,1),t,if(lt(t,4),1,5-t))':eval=frame")
            
            audio_filter_str = ",".join(audio_filters) if audio_filters else "anull"
            
            audio_input = [
                "-f", "lavfi",
                "-i", f"sine=frequency=1000:duration={duration}",
                "-af", audio_filter_str,
            ]
        elif audio_varying:
            # Audio that varies in volume
            audio_input = [
                "-f", "lavfi",
                "-i", f"sine=frequency=1000:duration={duration}",
                "-af", "volume='if(lt(t,1),t,if(lt(t,4),1,5-t))':eval=frame",
            ]
        else:
            # Constant audio
            audio_input = [
                "-f", "lavfi",
                "-i", f"sine=frequency=1000:duration={duration}",
            ]
    else:
        audio_input = []
    
    # Output settings
    output_settings = [
        "-c:v", "libx264",
        "-preset", "ultrafast",  # Fast encoding for tests
        "-crf", "28",  # Lower quality = smaller file
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-y",  # Overwrite output
        str(output_path),
    ]
    
    if audio:
        output_settings = [
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ]
    else:
        output_settings = [
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-pix_fmt", "yuv420p",
            "-an",  # No audio
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ]
    
    cmd = ["ffmpeg"] + video_input + audio_input + output_settings
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")


def generate_all_fixtures(fixtures_dir: Path) -> None:
    """Generate all test fixture videos.
    
    Args:
        fixtures_dir: Directory to save fixtures
    """
    fixtures_dir = Path(fixtures_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    
    print("Generating test video fixtures...")
    
    # 1. Basic vertical video with audio (5 seconds)
    print("  - sample_vertical.mp4 (5s, with audio)")
    generate_test_video(
        fixtures_dir / "sample_vertical.mp4",
        duration=5.0,
        width=1080,
        height=1920,
        audio=True,
    )
    
    # 2. Video with silence sections (silence at 1-2s and 3-4s)
    print("  - sample_with_silence.mp4 (5s, with silence sections)")
    generate_test_video(
        fixtures_dir / "sample_with_silence.mp4",
        duration=5.0,
        width=1080,
        height=1920,
        audio=True,
        silence_sections=[(1.0, 2.0), (3.0, 4.0)],
    )
    
    # 3. Video with varying audio levels
    print("  - sample_varying_audio.mp4 (5s, varying volume)")
    generate_test_video(
        fixtures_dir / "sample_varying_audio.mp4",
        duration=5.0,
        width=1080,
        height=1920,
        audio=True,
        audio_varying=True,
    )
    
    # 4. Video without audio
    print("  - sample_no_audio.mp4 (5s, no audio)")
    generate_test_video(
        fixtures_dir / "sample_no_audio.mp4",
        duration=5.0,
        width=1080,
        height=1920,
        audio=False,
    )
    
    # 5. Short video for quick tests (2 seconds)
    print("  - sample_short.mp4 (2s, with audio)")
    generate_test_video(
        fixtures_dir / "sample_short.mp4",
        duration=2.0,
        width=1080,
        height=1920,
        audio=True,
    )
    
    # 6. Horizontal video (for variety)
    print("  - sample_horizontal.mp4 (5s, 1920x1080)")
    generate_test_video(
        fixtures_dir / "sample_horizontal.mp4",
        duration=5.0,
        width=1920,
        height=1080,
        audio=True,
    )
    
    print(f"\nAll fixtures generated in: {fixtures_dir}")
    
    # List generated files with sizes
    for f in sorted(fixtures_dir.glob("*.mp4")):
        size = f.stat().st_size / 1024  # KB
        print(f"  {f.name}: {size:.1f} KB")


if __name__ == "__main__":
    import sys
    
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    if len(sys.argv) > 1:
        fixtures_dir = Path(sys.argv[1])
    
    generate_all_fixtures(fixtures_dir)
