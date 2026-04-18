"""Targeted regression tests for FFmpeg transcode command builders."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg.transcode import build_silence_removed_audio_command


def test_shared_trim_script_video_output_is_routed_to_null_muxer(tmp_path: Path) -> None:
    output_audio = tmp_path / "snippet.ogg"
    cmd = build_silence_removed_audio_command(
        input_file=Path("input.mkv"),
        output_audio_path=output_audio,
        filter_script_path=tmp_path / "shared.ffscript",
        acodec=["-c:a", "libopus", "-b:a", "32k"],
        has_video_output=True,
        max_duration=180.0,
    )

    output_index = cmd.index(str(output_audio))

    assert cmd.count("-map") == 2
    assert cmd[output_index + 1 :] == ["-map", "[outv]", "-t", "180.0", "-f", "null", "-"]


def test_audio_only_trim_script_keeps_single_output(tmp_path: Path) -> None:
    output_audio = tmp_path / "snippet.ogg"
    cmd = build_silence_removed_audio_command(
        input_file=Path("input.mkv"),
        output_audio_path=output_audio,
        filter_script_path=tmp_path / "audio_only.ffscript",
        acodec=["-c:a", "libopus"],
        has_video_output=False,
    )

    assert cmd.count("-map") == 1
    assert cmd[-1] == str(output_audio)
    assert "null" not in cmd
