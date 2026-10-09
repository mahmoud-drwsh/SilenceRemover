"""Final videos must play in current browsers: HEVC with the hvc1 tag, a sane level, and faststart."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from src.ffmpeg.encoding_resolver import get_encoder_config
from src.ffmpeg.transcode import build_final_trim_command
from src.ffmpeg.trim_script_bundle import write_trim_script_from_plan
from src.media.trim import set_metadata_title, trim_single_video

# HEVC level 4.1 (level_idc 123) covers 1080p at 60 fps. Many hardware decoders refuse level 6.x.
MAX_BROWSER_LEVEL_IDC = 123

needs_x265 = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    or "libx265" not in subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout,
    reason="ffmpeg with libx265 is required",
)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,codec_tag_string,level,avg_frame_rate:format_tags=title",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def _video_stream(info: dict) -> dict:
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def _moov_before_mdat(path: Path) -> bool:
    data = path.read_bytes()
    return 0 <= data.find(b"moov") < data.find(b"mdat")


def test_x265_uses_fast_preset_and_crf_22() -> None:
    args = get_encoder_config("X265")["args"]
    assert args[:4] == ["-crf", "22", "-preset", "fast"]


@pytest.mark.parametrize("encoder", ["X265", "QSV", "VAAPI", "AMF"])
def test_final_command_sets_frame_rate_hvc1_tag_and_faststart(tmp_path: Path, encoder: str) -> None:
    cmd = build_final_trim_command(
        input_file=Path("input.mp4"), output_file=tmp_path / "out.mp4",
        filter_script_path=tmp_path / "final.ffscript", encoder=encoder, frame_rate="30/1",
    )
    joined = " ".join(cmd)
    assert "-fps_mode cfr -r 30/1" in joined
    assert "-tag:v hvc1" in joined
    assert "-movflags +faststart" in joined


def test_final_command_without_known_frame_rate_does_not_force_one(tmp_path: Path) -> None:
    cmd = build_final_trim_command(
        input_file=Path("input.mp4"), output_file=tmp_path / "out.mp4",
        filter_script_path=tmp_path / "final.ffscript", encoder="X265",
    )
    assert "-r" not in cmd
    assert "-fps_mode" not in cmd


def _make_source(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
         "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )


@needs_x265
def test_trimmed_video_is_browser_playable_hevc(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _make_source(source)
    script = write_trim_script_from_plan(
        input_file=source, temp_dir=tmp_path, target_length=None, noise_threshold=-60,
        min_duration=0.7, pad_sec=0.2, segments_to_keep=[(0.2, 1.5), (2.0, 3.6)],
    )

    output = trim_single_video(
        input_file=source, output_dir=tmp_path / "out", noise_threshold=-60, min_duration=0.7,
        pad_sec=0.2, target_length=None, output_basename="final", encoder="X265",
        temp_dir=tmp_path / "work", metadata_title="عنوان", trim_script_path=script,
    )

    info = _probe(output)
    video = _video_stream(info)
    assert video["codec_name"] == "hevc"
    assert video["codec_tag_string"] == "hvc1"
    assert video["avg_frame_rate"] == "30/1"
    assert 0 < int(video["level"]) <= MAX_BROWSER_LEVEL_IDC
    assert info["format"]["tags"]["title"] == "عنوان"
    assert _moov_before_mdat(output)


@needs_x265
def test_title_remux_gives_hev1_files_the_hvc1_tag(tmp_path: Path) -> None:
    video = tmp_path / "prerender.mp4"
    _make_source(video)
    assert _video_stream(_probe(video))["codec_tag_string"] == "hev1"

    set_metadata_title(video, "Approved")

    info = _probe(video)
    assert _video_stream(info)["codec_tag_string"] == "hvc1"
    assert info["format"]["tags"]["title"] == "Approved"
    assert _moov_before_mdat(video)
