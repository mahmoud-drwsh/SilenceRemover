"""Container-safety regression tests for the final-video copy shortcut."""

from pathlib import Path

from src.ffmpeg.trim_script_bundle import TrimScriptArtifact
from src.media import trim


def _copy_artifact(tmp_path: Path) -> TrimScriptArtifact:
    script = tmp_path / "copy.ffscript"
    script.write_text("[0:v]null[outv]", encoding="utf-8")
    return TrimScriptArtifact(script_path=script, final_strategy="copy", filter_graph="[0:v]null[outv]")


def test_copy_strategy_reencodes_mkv_to_a_real_mp4(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.mkv"
    input_file.write_bytes(b"matroska bytes")
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"
    artifact = _copy_artifact(tmp_path)
    encoded: list[Path] = []

    monkeypatch.setattr(trim, "load_trim_script", lambda *_args, **_kwargs: artifact)
    monkeypatch.setattr(trim, "resolve_prepared_video_overlays", lambda **_kwargs: (None, None, 0, False))
    monkeypatch.setattr(trim, "wait_for_file_release", lambda _path: None)

    def encode(*, output_file: Path, **_kwargs) -> None:
        encoded.append(output_file)
        output_file.write_bytes(b"mp4 bytes")

    monkeypatch.setattr(trim, "run_silence_removed_media_with_script", encode)

    result = trim.trim_single_video(
        input_file=input_file, output_dir=output_dir, noise_threshold=-55, min_duration=0.1,
        pad_sec=0.1, target_length=None, temp_dir=temp_dir, trim_script_path=artifact.script_path,
    )

    assert result.suffix == ".mp4"
    assert result.read_bytes() == b"mp4 bytes"
    assert len(encoded) == 1


def test_copy_strategy_keeps_mp4_copy_shortcut(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"mp4 bytes")
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"
    artifact = _copy_artifact(tmp_path)

    monkeypatch.setattr(trim, "load_trim_script", lambda *_args, **_kwargs: artifact)
    monkeypatch.setattr(trim, "resolve_prepared_video_overlays", lambda **_kwargs: (None, None, 0, False))
    monkeypatch.setattr(trim, "wait_for_file_release", lambda _path: None)
    monkeypatch.setattr(trim, "run_silence_removed_media_with_script", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must copy MP4")))

    result = trim.trim_single_video(
        input_file=input_file, output_dir=output_dir, noise_threshold=-55, min_duration=0.1,
        pad_sec=0.1, target_length=None, temp_dir=temp_dir, trim_script_path=artifact.script_path,
    )

    assert result.read_bytes() == b"mp4 bytes"
