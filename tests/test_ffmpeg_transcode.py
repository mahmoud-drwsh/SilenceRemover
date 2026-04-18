"""Targeted regression tests for FFmpeg transcode command builders."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg.transcode import build_silence_removed_audio_command


def test_audio_trim_command_maps_only_audio_output(tmp_path: Path) -> None:
    output_audio = tmp_path / "snippet.ogg"
    cmd = build_silence_removed_audio_command(
        input_file=Path("input.mkv"),
        output_audio_path=output_audio,
        filter_script_path=tmp_path / "audio_only.ffscript",
        acodec=["-c:a", "libopus", "-b:a", "32k"],
        max_duration=180.0,
    )

    assert cmd.count("-map") == 1
    assert "[outa]" in cmd
    assert "[outv]" not in cmd
    assert cmd[-1] == str(output_audio)


def test_audio_trim_command_has_no_null_muxer_fallback(tmp_path: Path) -> None:
    output_audio = tmp_path / "snippet.ogg"
    cmd = build_silence_removed_audio_command(
        input_file=Path("input.mkv"),
        output_audio_path=output_audio,
        filter_script_path=tmp_path / "audio_only.ffscript",
        acodec=["-c:a", "libopus"],
    )

    assert cmd.count("-map") == 1
    assert "null" not in cmd
    assert cmd[-1] == str(output_audio)
