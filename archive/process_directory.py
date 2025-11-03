#!/usr/bin/env python3
"""
Batch process all videos in a directory to remove silence segments.

This script finds all video files in a directory and processes each one
using the remove_silence.py script.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Common video file extensions
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', 
                    '.m4v', '.mpg', '.mpeg', '.3gp', '.ogv', '.ts', '.m2ts'}


def is_video_file(file_path: Path) -> bool:
    """Check if a file is a video file based on extension."""
    return file_path.suffix.lower() in VIDEO_EXTENSIONS


def find_video_files(directory: Path) -> list[Path]:
    """Find all video files in a directory (non-recursive)."""
    video_files = []
    if not directory.exists():
        print(f"Error: Directory '{directory}' does not exist", file=sys.stderr)
        return video_files
    
    if not directory.is_dir():
        print(f"Error: '{directory}' is not a directory", file=sys.stderr)
        return video_files
    
    for item in directory.iterdir():
        if item.is_file() and is_video_file(item):
            video_files.append(item)
    
    return sorted(video_files)


def process_directory(
    input_dir: Path,
    script_path: Path,
    target_length: float | None,
):
    """Process all videos in the input directory."""
    video_files = find_video_files(input_dir)
    
    if not video_files:
        print(f"No video files found in '{input_dir}'")
        return
    
    # Resolve sibling folders next to input
    output_dir = input_dir.parent / "trimmed"
    # Load configuration from .env file with defaults
    noise_threshold = float(os.getenv('NOISE_THRESHOLD', '-30.0'))
    min_duration = float(os.getenv('MIN_DURATION', '0.5'))
    pad = float(os.getenv('PAD', '0.5'))
    
    print(f"Found {len(video_files)} video file(s) to process")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    tl_str = f", target={target_length}s" if target_length is not None else ""
    print(f"Settings: noise={noise_threshold}dB, min_duration={min_duration}s, pad={pad}s{tl_str}")
    print("-" * 60)
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each video file
    for i, video_file in enumerate(video_files, 1):
        print(f"\n[{i}/{len(video_files)}] Processing: {video_file.name}")
        
        cmd = [
            'uv', 'run', 'python',
            str(script_path),
            str(video_file),
            '-o', str(output_dir)
        ]
        if target_length is not None:
            cmd += ['--target-length', str(target_length)]
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=False)
            print(f"✓ Successfully processed: {video_file.name}")
        except subprocess.CalledProcessError as e:
            print(f"✗ Error processing {video_file.name}: {e}", file=sys.stderr)
            continue
    
    print("\n" + "=" * 60)
    print(f"Processing complete! {len(video_files)} file(s) processed")
    print(f"Output files saved to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description='Batch process all videos in a directory to remove silence segments',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python process_directory.py /path/to/videos --output-dir ./output
  uv run python process_directory.py ./videos -o ./processed --target-length 170
        """
    )
    parser.add_argument('input_dir', type=Path,
                        help='Input directory containing video files')
    # No explicit output flag; write to sibling 'trimmed'
    parser.add_argument('--target-length', type=float, default=None,
                        help='Target output duration (seconds) for each video. Passed to remove_silence.py')
    parser.add_argument('--script', type=Path, default=None,
                        help='Path to remove_silence.py script (default: same directory as this script)')
    
    parser.epilog = """
Examples:
  uv run python process_directory.py /path/to/videos --output-dir ./output
  uv run python process_directory.py ./videos -o ./processed --target-length 170
  
Configuration is loaded from .env file:
  NOISE_THRESHOLD=-30.0
  MIN_DURATION=0.5
  PAD=0.5
        """
    
    args = parser.parse_args()
    
    # Determine the path to remove_silence.py
    if args.script:
        script_path = args.script
    else:
        # Default to remove_silence.py in the same directory as this script
        script_path = Path(__file__).parent / 'remove_silence.py'
    
    if not script_path.exists():
        print(f"Error: remove_silence.py not found at '{script_path}'", file=sys.stderr)
        print(f"Please specify the correct path with --script", file=sys.stderr)
        sys.exit(1)
    
    process_directory(
        args.input_dir,
        script_path,
        args.target_length,
    )


if __name__ == '__main__':
    main()

