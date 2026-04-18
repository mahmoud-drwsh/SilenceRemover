"""Regression tests for trim script bundle artifacts."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "packages"))

from sr_trim_plan import TrimPlan
from src.ffmpeg import trim_script_bundle


def _plan(
    *,
    segments_to_keep: list[tuple[float, float]],
    should_copy_input: bool = False,
) -> TrimPlan:
    resulting_length_sec = sum(end - start for start, end in segments_to_keep)
    input_duration_sec = segments_to_keep[-1][1] if segments_to_keep else 3.0
    return TrimPlan(
        mode="non_target",
        segments_to_keep=segments_to_keep,
        input_duration_sec=input_duration_sec,
        resulting_length_sec=resulting_length_sec,
        resolved_noise_threshold=-55.0,
        resolved_min_duration=0.01,
        resolved_pad_sec=0.5,
        target_length=None,
        should_copy_input=should_copy_input,
    )


def test_generate_trim_script_writes_final_and_snippet_scripts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "input.mkv"
    input_file.write_bytes(b"video")
    plan = _plan(segments_to_keep=[(0.0, 1.0), (2.0, 3.0)])

    monkeypatch.setattr(trim_script_bundle, "build_trim_plan", lambda **_kwargs: plan)
    monkeypatch.setattr(trim_script_bundle, "probe_has_audio_stream", lambda _path: True)

    final_script_path = trim_script_bundle.generate_trim_script(
        input_file=input_file,
        temp_dir=tmp_path,
        target_length=None,
        noise_threshold=-55.0,
        min_duration=0.01,
        pad_sec=0.5,
    )
    snippet_script_path = trim_script_bundle.get_snippet_trim_script_path_from_final(final_script_path)

    final_graph = final_script_path.read_text(encoding="utf-8")
    snippet_graph = snippet_script_path.read_text(encoding="utf-8")

    assert "concat=n=2:v=1:a=1[outv][outa]" in final_graph
    assert "concat=n=2:v=0:a=1[outa]" in snippet_graph
    assert "[outv]" not in snippet_graph


def test_is_trim_script_ready_derives_missing_snippet_without_reanalysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "input.mkv"
    input_file.write_bytes(b"video")
    final_script_path = trim_script_bundle.get_trim_script_path(
        input_file=input_file,
        temp_dir=tmp_path,
        target_length=None,
        noise_threshold=-55.0,
        min_duration=0.01,
        pad_sec=0.5,
    )
    final_script_path.write_text(
        "[0:v]trim=start=0.0:end=1.0,setpts=PTS-STARTPTS[v0];"
        "[0:a]atrim=start=0.0:end=1.0,asetpts=PTS-STARTPTS[a0];"
        "[v0][a0]concat=n=1:v=1:a=1[outv][outa]",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        trim_script_bundle,
        "build_trim_plan",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("build_trim_plan should not run")),
    )

    assert trim_script_bundle.is_trim_script_ready(
        input_file=input_file,
        temp_dir=tmp_path,
        target_length=None,
        noise_threshold=-55.0,
        min_duration=0.01,
        pad_sec=0.5,
    )

    snippet_script_path = trim_script_bundle.get_snippet_trim_script_path_from_final(final_script_path)
    assert snippet_script_path.exists()
    assert snippet_script_path.read_text(encoding="utf-8") == (
        "[0:a]atrim=start=0.0:end=1.0,asetpts=PTS-STARTPTS[a0];"
        "[a0]concat=n=1:v=0:a=1[outa]"
    )


def test_derive_snippet_trim_script_handles_video_only_final_graph(tmp_path: Path) -> None:
    final_script_path = tmp_path / "silent.ffscript"
    final_script_path.write_text(
        "[0:v]trim=start=1.0:end=2.5,setpts=PTS-STARTPTS[v0];"
        "anullsrc=channel_layout=stereo:sample_rate=48000,atrim=start=0:end=1.5,asetpts=PTS-STARTPTS[a0];"
        "[v0][a0]concat=n=1:v=1:a=1[outv][outa]",
        encoding="utf-8",
    )

    snippet_script_path = trim_script_bundle.derive_snippet_trim_script(final_script_path)
    snippet_graph = snippet_script_path.read_text(encoding="utf-8")

    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in snippet_graph
    assert "concat=n=1:v=0:a=1[outa]" in snippet_graph
    assert "[0:v]" not in snippet_graph
