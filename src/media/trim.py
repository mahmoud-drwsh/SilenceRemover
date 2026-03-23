"""Video trimming functionality."""

import shutil
import time
from pathlib import Path
from typing import Callable, Optional

from src.core.constants import (
    DEFAULT_LOGO_PATH,
    LOGO_OVERLAY_ALPHA,
    LOGO_OVERLAY_MARGIN_PX,
    LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO,
    TITLE_BANNER_HEIGHT_FRACTION,
    TITLE_BANNER_START_FRACTION,
    TITLE_FONT_DEFAULT,
)
from src.ffmpeg.encoding_resolver import VideoEncoderProfile, resolve_video_encoder
from src.ffmpeg.filter_graph import (
    build_video_audio_concat_filter_graph,
    build_video_audio_concat_filter_graph_with_title_overlay,
    build_video_lavfi_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph_with_title_overlay,
)
from src.ffmpeg.probing import (
    probe_ffmpeg_can_decode_image_frame,
    probe_has_audio_stream,
    probe_video_dimensions,
)
from sr_trim_plan import build_trim_plan
from sr_title_overlay import build_title_overlay
from src.ffmpeg.transcode import build_final_trim_command, build_minimal_video_command
from src.core.fs_utils import wait_for_file_release
from src.ffmpeg.core import build_ffmpeg_cmd
from src.ffmpeg.silence_removed_runner import (
    run_minimal_ffmpeg_output,
    run_silence_removed_media,
)
from src.ffmpeg.runner import run
from src.core.paths import get_font_cache_path, get_title_overlay_path


def _copy_input_video(input_file: Path, output_file: Path) -> Path:
    print(
        f"Target length >= original duration, copying original file "
        f"{input_file} -> {output_file}"
    )
    try:
        shutil.copyfile(input_file, output_file)
        return output_file.resolve()
    except Exception as exc:
        raise RuntimeError(f"Failed to copy original file from {input_file} to {output_file}") from exc


def _get_prescaled_logo_path(temp_dir: Path, *, target_width_px: int) -> Path:
    """Return a deterministic cached logo path for a target width."""
    logo_dir = temp_dir / "logo_overlays"
    logo_dir.mkdir(parents=True, exist_ok=True)
    return logo_dir / f"logo_w{target_width_px}.png"


def _ensure_prescaled_logo(
    *,
    source_logo_path: Path,
    output_logo_path: Path,
    target_width_px: int,
) -> Path:
    """Create or reuse a pre-scaled logo PNG at the requested width."""
    if target_width_px <= 0:
        raise RuntimeError(f"Invalid target logo width: {target_width_px}")

    if output_logo_path.is_file():
        try:
            w, _ = probe_video_dimensions(output_logo_path)
            probe_ffmpeg_can_decode_image_frame(output_logo_path)
            if w == target_width_px:
                return output_logo_path
        except (OSError, RuntimeError, ValueError):
            # Regenerate corrupted or mismatched cache entry.
            pass

    cmd = build_ffmpeg_cmd(
        overwrite=True,
        "-v",
        "error",
        "-i",
        str(source_logo_path),
        "-vf",
        f"scale={target_width_px}:-1:flags=lanczos,format=rgba",
        "-frames:v",
        "1",
        str(output_logo_path),
    )
    result = run(cmd, check=False, capture_output=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip()
        if len(tail) > 400:
            tail = f"{tail[:400]}..."
        raise RuntimeError(tail or f"Failed to pre-scale logo: {source_logo_path}")

    return output_logo_path


def trim_single_video(
    input_file: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    output_basename: Optional[str] = None,
    encoder: VideoEncoderProfile | None = None,
    title_path: Path | None = None,
    title_font: str | None = None,
    max_output_seconds: float | None = None,
) -> Path:
    """Trim a single video and return the output file path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    basename = output_basename if output_basename is not None else input_file.stem
    output_file = (output_dir / f"{basename}.mp4").resolve()

    plan = build_trim_plan(
        input_file=input_file,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )

    use_logo = DEFAULT_LOGO_PATH.is_file()
    logo_path_resolved = DEFAULT_LOGO_PATH if use_logo else None

    if plan.should_copy_input and title_path is None and not use_logo:
        copied_output_file = _copy_input_video(input_file=input_file, output_file=output_file)
        wait_for_file_release(copied_output_file)
        return copied_output_file

    segments_to_keep = plan.segments_to_keep
    duration_sec = plan.input_duration_sec
    resolved_noise_threshold = plan.resolved_noise_threshold
    resolved_min_duration = plan.resolved_min_duration
    resolved_pad_sec = plan.resolved_pad_sec
    encoder = encoder or resolve_video_encoder()
    use_qsv_hardware_path = encoder.codec == "hevc_qsv"
    resulting_length = plan.resulting_length_sec
    input_has_audio = probe_has_audio_stream(input_file)
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"Settings: noise={resolved_noise_threshold}dB, min_duration={resolved_min_duration}s, pad={resolved_pad_sec}s")
    print(f"Number of segments: {len(segments_to_keep)}")

    if target_length is not None:
        print(f"Target length: {target_length}s")
        print(f"Expected resulting length: {resulting_length:.3f}s")

    font_name = title_font or TITLE_FONT_DEFAULT
    temp_dir = output_dir / "temp"
    title_overlay_path: Path | None = None
    banner_top: int | None = None
    logo_target_w: int | None = None

    if title_path is not None or use_logo:
        video_width, video_height = probe_video_dimensions(input_file)
        if use_logo:
            try:
                _lw, _lh = probe_video_dimensions(DEFAULT_LOGO_PATH)
                probe_ffmpeg_can_decode_image_frame(DEFAULT_LOGO_PATH)
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"Warning: Skipping logo overlay ({DEFAULT_LOGO_PATH}): {exc}")
                use_logo = False
                logo_path_resolved = None
            else:
                logo_target_w = max(1, int(video_width * LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO))
                try:
                    logo_path_resolved = _ensure_prescaled_logo(
                        source_logo_path=DEFAULT_LOGO_PATH,
                        output_logo_path=_get_prescaled_logo_path(
                            temp_dir=temp_dir, target_width_px=logo_target_w
                        ),
                        target_width_px=logo_target_w,
                    )
                except RuntimeError as exc:
                    print(f"Warning: Skipping logo overlay pre-scale ({DEFAULT_LOGO_PATH}): {exc}")
                    use_logo = False
                    logo_path_resolved = None

    if title_path is not None:
        title_text = title_path.read_text(encoding="utf-8").strip()
        if not title_text:
            raise RuntimeError(f"Empty title at {title_path}")
        banner_height = max(1, int(video_height * TITLE_BANNER_HEIGHT_FRACTION))
        banner_top = int(video_height * TITLE_BANNER_START_FRACTION)
        title_overlay_path = build_title_overlay(
            title=title_text,
            video_width=video_width,
            banner_height=banner_height,
            output_file=get_title_overlay_path(temp_dir, basename),
            font_family=font_name,
            font_cache_dir=get_font_cache_path(temp_dir),
        )

    # Handle case where all audio is silence (no segments to keep)
    if len(segments_to_keep) == 0:
        print("Warning: All audio detected as silence. Creating minimal video (first frame only).")
        # Create minimal video with first frame and silence using the resolved encoder profile.
        def _run_minimal_encode(*, use_hw_path: bool) -> Path:
            return run_minimal_ffmpeg_output(
                output_file=output_file,
                cmd=build_minimal_video_command(
                    input_file=input_file,
                    output_file=output_file,
                    encoder=encoder,
                    title_overlay_path=title_overlay_path,
                    title_overlay_y=banner_top,
                    logo_path=logo_path_resolved if use_logo else None,
                    logo_enabled=use_logo,
                    logo_margin_px=LOGO_OVERLAY_MARGIN_PX,
                    logo_alpha=LOGO_OVERLAY_ALPHA,
                    source_metadata_filename=(
                        input_file.name
                        if (title_overlay_path is not None or use_logo)
                        else None
                    ),
                    use_qsv_hardware_path=use_hw_path,
                ),
                command_label=f"{encoder.codec} encode",
            )

        if use_qsv_hardware_path:
            try:
                return _run_minimal_encode(use_hw_path=True)
            except RuntimeError as exc:
                print(
                    "Warning: QSV hardware-path flags failed for minimal encode; "
                    "retrying with generic FFmpeg input path. "
                    f"Original error: {exc}"
                )
                return _run_minimal_encode(use_hw_path=False)

        return _run_minimal_encode(use_hw_path=False)

    burn_in = title_overlay_path is not None or use_logo

    def _graph_with_optional_burn_in(segs: list[tuple[float, float]], oy: int | None) -> str:
        oy_eff = oy if title_overlay_path is not None else None
        kw = dict(
            logo_enabled=use_logo,
            logo_margin_px=LOGO_OVERLAY_MARGIN_PX,
            logo_alpha=LOGO_OVERLAY_ALPHA,
        )
        if input_has_audio:
            return build_video_audio_concat_filter_graph_with_title_overlay(segs, oy_eff, **kw)
        return build_video_lavfi_audio_concat_filter_graph_with_title_overlay(segs, oy_eff, **kw)

    if burn_in:
        filter_builder = _graph_with_optional_burn_in
        use_lavfi_silent_audio = not input_has_audio
    else:
        filter_builder = (
            build_video_audio_concat_filter_graph
            if input_has_audio
            else build_video_lavfi_audio_concat_filter_graph
        )
        use_lavfi_silent_audio = not input_has_audio

    start_wall = time.monotonic()

    def _on_progress(percent: int, ffmpeg_elapsed_sec: float) -> None:
        wall_elapsed = time.monotonic() - start_wall
        speed_x = ffmpeg_elapsed_sec / max(wall_elapsed, 1e-6)
        size_txt = "n/a"
        try:
            size_mb = output_file.stat().st_size / 1048576
            size_txt = f"{size_mb:.2f} MiB"
        except OSError:
            pass

        print(
            f"\rProgress: {percent}% | {wall_elapsed:.1f}s wall | {ffmpeg_elapsed_sec:.1f}s encoded | {speed_x:.2f}x | {size_txt}",
            end="",
            flush=True,
        )

    def _run_final_encode(*, use_hw_path: bool) -> Path:
        return run_silence_removed_media(
            input_file=input_file,
            output_file=output_file,
            temp_dir=output_dir / "temp",
            segments_to_keep=segments_to_keep,
            build_filter_graph=filter_builder,
            build_command=lambda in_file, out_file, filter_script: build_final_trim_command(
                input_file=in_file,
                output_file=out_file,
                filter_script_path=filter_script,
                encoder=encoder,
                title_overlay_path=title_overlay_path,
                title_overlay_y=banner_top,
                logo_path=logo_path_resolved if use_logo else None,
                extra_silent_audio_lavfi=use_lavfi_silent_audio,
                source_metadata_filename=(
                    in_file.name if (title_overlay_path is not None or use_logo) else None
                ),
                max_output_seconds=max_output_seconds,
                use_qsv_hardware_path=use_hw_path,
            ),
            expected_total_seconds=resulting_length if resulting_length > 0 else duration_sec,
            on_progress=_on_progress,
            command_label=f"{encoder.codec} encode",
            overlay_y=banner_top,
        )

    if use_qsv_hardware_path:
        try:
            return _run_final_encode(use_hw_path=True)
        except RuntimeError as exc:
            print(
                "Warning: QSV hardware-path flags failed during encode; "
                "retrying with generic FFmpeg input path. "
                f"Original error: {exc}"
            )
            return _run_final_encode(use_hw_path=False)

    return _run_final_encode(use_hw_path=False)

