"""Video trimming functionality."""

import shutil
from pathlib import Path
from typing import Optional

from src.core.constants import SCRIPTS_DIR
from src.ffmpeg.encoding_resolver import get_encoder_config
from src.ffmpeg.transcode import build_final_trim_command
from src.core.fs_utils import wait_for_file_release
from src.ffmpeg.core import build_ffmpeg_cmd
from src.ffmpeg.silence_removed_runner import (
    run_silence_removed_media_with_script,
)
from src.ffmpeg.filter_graph import write_filter_graph_script
from src.ffmpeg.trim_script_bundle import load_trim_script
from src.ffmpeg.runner import run
from src.core.paths import get_processing_video_path


def _copy_input_video(
    input_file: Path,
    output_file: Path,
    temp_dir: Path,
    basename: str,
) -> Path:
    """Copy input video to output using processing file → final rename pattern."""
    processing_output = get_processing_video_path(temp_dir, basename)
    processing_output.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copyfile(input_file, processing_output)
        _move_processing_to_final(processing_output, output_file)
        # Delete from processing after successful move
        if processing_output.exists():
            processing_output.unlink()
        return output_file.resolve()
    except Exception as exc:
        raise RuntimeError(f"Failed to copy original file from {input_file} to {output_file}") from exc


def set_metadata_title(video_path: Path, title: str) -> None:
    """Set the container title with a stream copy. Do not re-encode video or audio."""
    replacement = video_path.with_name(f"{video_path.stem}.titled.mp4")
    cmd = build_ffmpeg_cmd(
        True, "-v", "error", "-i", str(video_path), "-map", "0", "-c", "copy",
        "-metadata", f"title={title}", "-movflags", "+faststart", str(replacement),
    )
    try:
        run(cmd, capture_output=True)
        replacement.replace(video_path)
    finally:
        replacement.unlink(missing_ok=True)


def _move_processing_to_final(processing_path: Path, final_path: Path) -> None:
    """Atomically rename processing file to final path, with copy fallback.
    
    On success: final_path exists, processing_path does not exist.
    On failure: raises RuntimeError, processing_path may still exist.
    """
    try:
        processing_path.rename(final_path)
    except OSError:
        # Rename failed (different filesystems, Windows with open handles, etc.)
        # Fallback to copy + delete
        try:
            shutil.copy2(processing_path, final_path)
            processing_path.unlink()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to move processing file {processing_path} to final {final_path}: {exc}"
            ) from exc


def _with_vaapi_upload_filter(script_path: Path, temp_dir: Path, basename: str) -> Path:
    """Append VAAPI upload inside the existing complex graph, not as a conflicting -vf."""
    graph = script_path.read_text(encoding="utf-8").strip()
    marker = "[outv]"
    if marker not in graph:
        raise RuntimeError(f"VAAPI filter graph does not expose {marker}: {script_path}")
    prefix, suffix = graph.rsplit(marker, 1)
    vaapi_graph = f"{prefix}[outv_sw]{suffix};[outv_sw]format=nv12,hwupload[outv]"
    scripts_dir = temp_dir / SCRIPTS_DIR
    scripts_dir.mkdir(parents=True, exist_ok=True)
    return write_filter_graph_script(scripts_dir / f"{basename}_vaapi.ffscript", vaapi_graph)


def trim_single_video(
    input_file: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    output_basename: Optional[str] = None,
    encoder: str = "libx265",
    temp_dir: Optional[Path] = None,
    metadata_title: str | None = None,
    trim_script_path: Path | None = None,
) -> Path:
    """Trim a single video and return the output file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_basename if output_basename is not None else input_file.stem
    output_file = (output_dir / f"{basename}.mp4").resolve()
    temp_dir_resolved = temp_dir if temp_dir is not None else output_dir / "temp"
    temp_dir_resolved.mkdir(parents=True, exist_ok=True)

    if trim_script_path is None:
        raise RuntimeError("trim_single_video requires a pre-generated trim script")
    artifact = load_trim_script(
        trim_script_path,
        input_file=input_file,
        target_length=target_length,
    )

    encoder = encoder or get_encoder_config("X265")["codec"]
    use_qsv_hardware_path = encoder.upper() == "QSV"
    use_vaapi_hardware_path = encoder.upper() == "VAAPI"

    if (
        artifact.final_strategy == "copy"
        and input_file.suffix.lower() == ".mp4"
    ):
        copied_output_file = _copy_input_video(
            input_file=input_file,
            output_file=output_file,
            temp_dir=temp_dir_resolved,
            basename=basename,
        )
        wait_for_file_release(copied_output_file)
        if metadata_title:
            # The copy shortcut does not encode, so it must write the title here.
            set_metadata_title(copied_output_file, metadata_title)
        return copied_output_file

    def _run_final_encode(*, use_hw_path: bool) -> Path:
        processing_output = get_processing_video_path(temp_dir_resolved, basename)
        processing_output.parent.mkdir(parents=True, exist_ok=True)
        final_filter_script_path = artifact.script_path
        if use_vaapi_hardware_path:
            final_filter_script_path = _with_vaapi_upload_filter(
                final_filter_script_path, temp_dir_resolved, basename
            )

        def _build_ffmpeg_command(in_file, out_file, filter_script):
            return build_final_trim_command(
                input_file=in_file,
                output_file=processing_output,
                filter_script_path=filter_script,
                encoder=encoder,
                use_qsv_hardware_path=use_hw_path,
                use_vaapi_hardware_path=use_vaapi_hardware_path,
                metadata_title=metadata_title,
            )

        run_silence_removed_media_with_script(
            input_file=input_file,
            output_file=processing_output,
            filter_script_path=final_filter_script_path,
            build_command=_build_ffmpeg_command,
            command_label=f"{encoder} encode",
        )
        _move_processing_to_final(processing_output, output_file)
        if processing_output.exists():
            processing_output.unlink()
        wait_for_file_release(output_file)
        return output_file.resolve()

    if use_qsv_hardware_path:
        try:
            return _run_final_encode(use_hw_path=True)
        except RuntimeError:
            return _run_final_encode(use_hw_path=False)

    return _run_final_encode(use_hw_path=False)
