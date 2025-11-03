from pathlib import Path
from typing import Optional
import subprocess
import sys
from .common import sibling_dir, is_video_file


def run(input_dir: Path, remove_silence_script: Path, target_length: Optional[float]) -> None:
    # Ensure trimmed dir exists
    output_dir = sibling_dir(input_dir, "trimmed")

    # Gather videos (non-recursive)
    videos = sorted(p for p in input_dir.iterdir() if is_video_file(p))
    if not videos:
        print(f"No video files found in '{input_dir}'")
        return

    print(f"Found {len(videos)} video file(s) to process")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print("-" * 60)

    for i, video_file in enumerate(videos, 1):
        print(f"\n[{i}/{len(videos)}] Processing: {video_file.name}")
        cmd = [
            'uv', 'run', 'python',
            str(remove_silence_script),
            str(video_file),
            '-o', str(output_dir),
        ]
        if target_length is not None:
            cmd += ['--target-length', str(target_length)]
        subprocess.run(cmd, check=True)


