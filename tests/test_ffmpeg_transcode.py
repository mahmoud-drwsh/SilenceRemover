"""Targeted regression tests for FFmpeg transcode command builders."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg.transcode import build_final_trim_command, build_silence_removed_audio_command
from src.media.trim import _with_vaapi_upload_filter


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


def test_vaapi_final_command_uses_render_node_and_uploads_filtered_frames(tmp_path: Path) -> None:
    cmd = build_final_trim_command(
        input_file=Path("input.mkv"), output_file=tmp_path / "output.mp4",
        filter_script_path=tmp_path / "final.ffscript", encoder="VAAPI",
        use_vaapi_hardware_path=True,
    )
    assert ["-vaapi_device", "/dev/dri/renderD128"] == cmd[3:5]
    assert "hevc_vaapi" in cmd
    assert "-vf" not in cmd


def test_vaapi_upload_is_appended_inside_complex_graph(tmp_path: Path) -> None:
    source = tmp_path / "source.ffscript"
    source.write_text("[0:v]null[outv];[0:a]anull[outa]", encoding="utf-8")
    result = _with_vaapi_upload_filter(source, tmp_path, "sample")
    assert result.read_text(encoding="utf-8") == (
        "[0:v]null[outv_sw];[0:a]anull[outa];[outv_sw]format=nv12,hwupload[outv]"
    )
