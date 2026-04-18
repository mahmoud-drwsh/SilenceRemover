"""Video trimming functionality."""

import shutil
from pathlib import Path
from typing import Optional

from src.core.constants import (
    DEFAULT_LOGO_PATH,
    LOGO_OVERLAY_ALPHA,
    LOGO_OVERLAY_MARGIN_PX,
    LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO,
    TITLE_BANNER_HEIGHT_FRACTION,
    TITLE_BANNER_START_FRACTION,
    TITLE_FONT_DEFAULT,
    SCRIPTS_DIR,
)
from src.ffmpeg.encoding_resolver import get_encoder_config
from src.ffmpeg.probing import (
    probe_ffmpeg_can_decode_image_frame,
    probe_video_dimensions,
)
from sr_title_overlay import build_title_overlay
from src.ffmpeg.transcode import build_final_trim_command
from src.core.fs_utils import wait_for_file_release
from src.ffmpeg.core import build_ffmpeg_cmd
from src.ffmpeg.silence_removed_runner import (
    run_silence_removed_media_with_script,
)
from src.ffmpeg.filter_graph import write_filter_graph_script
from src.ffmpeg.trim_script_bundle import load_trim_script
from src.ffmpeg.runner import run
from src.core.paths import get_font_cache_path, get_processing_video_path, get_title_overlay_path


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


def _build_overlay_suffix_from_base(
    *,
    title_overlay_y: int | None,
    logo_enabled: bool,
    logo_margin_px: int,
    logo_alpha: float,
) -> str:
    has_title = title_overlay_y is not None
    has_logo = bool(logo_enabled)
    if not has_title and not has_logo:
        return ""
    parts: list[str] = []
    base_label = "basev"
    logo_stream_idx = 2 if has_title else 1
    if has_logo:
        m = int(logo_margin_px)
        aa = float(logo_alpha)
        logo_out = "basev_logo"
        parts.append(
            f"[{logo_stream_idx}:v]format=rgba,colorchannelmixer=aa={aa}[ov_logo];"
            f"[{base_label}][ov_logo]overlay=W-w-{m}:{m}:shortest=1[{logo_out}]"
        )
        base_label = logo_out
    if has_title:
        oy = int(title_overlay_y)  # type: ignore[arg-type]
        title_out = "basev_title"
        parts.append(
            f"[1:v]format=rgba[ov_title];[{base_label}][ov_title]overlay=0:{oy}:shortest=1[{title_out}]"
        )
        base_label = title_out
    parts.append(f"[{base_label}]format=nv12[outv]")
    return ";" + ";".join(parts)


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
        True,
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


def _resolve_logo_target_width(input_file: Path) -> int:
    video_width, _video_height = probe_video_dimensions(input_file)
    return max(1, int(video_width * LOGO_OVERLAY_WIDTH_FRACTION_OF_VIDEO))


def is_logo_overlay_ready(
    input_file: Path,
    temp_dir: Path,
    enable_logo_overlay: bool,
) -> bool:
    """Return True when the expected pre-scaled logo asset file exists."""
    if not enable_logo_overlay or not DEFAULT_LOGO_PATH.is_file():
        return False

    try:
        target_width_px = _resolve_logo_target_width(input_file)
        candidate = _get_prescaled_logo_path(temp_dir, target_width_px=target_width_px)
        return candidate.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def prepare_title_overlay(
    input_file: Path,
    temp_dir: Path,
    title_path: Path | None,
    title_font: str | None,
    enable_title_overlay: bool,
    title_y_fraction: float | None,
    title_height_fraction: float | None,
) -> tuple[Path | None, int | None]:
    """Generate the title overlay PNG and return (path, banner_top)."""
    if title_path is None or not enable_title_overlay:
        return (None, None)

    try:
        title_text = title_path.read_text(encoding="utf-8").strip()
        if not title_text:
            return (None, None)

        video_width, video_height = probe_video_dimensions(input_file)
        font_name = title_font or TITLE_FONT_DEFAULT
        effective_height_fraction = (
            title_height_fraction
            if title_height_fraction is not None
            else TITLE_BANNER_HEIGHT_FRACTION
        )
        effective_start_fraction = (
            title_y_fraction
            if title_y_fraction is not None
            else TITLE_BANNER_START_FRACTION
        )
        banner_height = max(1, int(video_height * effective_height_fraction))
        banner_top = int(video_height * effective_start_fraction)
        basename = input_file.stem
        return (
            build_title_overlay(
                title=title_text,
                video_width=video_width,
                banner_height=banner_height,
                output_file=get_title_overlay_path(temp_dir, basename),
                font_family=font_name,
                font_cache_dir=get_font_cache_path(temp_dir),
            ),
            banner_top,
        )
    except (OSError, RuntimeError, ValueError):
        return (None, None)


def prepare_logo_overlay(
    input_file: Path,
    temp_dir: Path,
    enable_logo_overlay: bool,
) -> tuple[Path | None, bool]:
    """Generate or reuse the pre-scaled logo PNG and return (path, enabled)."""
    if not enable_logo_overlay or not DEFAULT_LOGO_PATH.is_file():
        return (None, False)

    try:
        probe_video_dimensions(DEFAULT_LOGO_PATH)
        probe_ffmpeg_can_decode_image_frame(DEFAULT_LOGO_PATH)
        target_width_px = _resolve_logo_target_width(input_file)
        return (
            _ensure_prescaled_logo(
                source_logo_path=DEFAULT_LOGO_PATH,
                output_logo_path=_get_prescaled_logo_path(
                    temp_dir=temp_dir,
                    target_width_px=target_width_px,
                ),
                target_width_px=target_width_px,
            ),
            True,
        )
    except (OSError, RuntimeError, ValueError):
        return (None, False)


def resolve_prepared_video_overlays(
    input_file: Path,
    temp_dir: Path,
    title_path: Path | None,
    enable_title_overlay: bool,
    enable_logo_overlay: bool,
    title_y_fraction: float | None,
    title_height_fraction: float | None,
) -> tuple[Path | None, Path | None, int | None, bool]:
    """Load pre-generated overlay assets for final encode."""
    title_overlay_path: Path | None = None
    logo_path_resolved: Path | None = None
    banner_top: int | None = None
    use_logo = False

    if title_path is not None and enable_title_overlay:
        title_text = title_path.read_text(encoding="utf-8").strip()
        if title_text:
            _video_width, video_height = probe_video_dimensions(input_file)
            effective_start_fraction = (
                title_y_fraction
                if title_y_fraction is not None
                else TITLE_BANNER_START_FRACTION
            )
            _effective_height_fraction = (
                title_height_fraction
                if title_height_fraction is not None
                else TITLE_BANNER_HEIGHT_FRACTION
            )
            banner_top = int(video_height * effective_start_fraction)
            title_overlay_candidate = get_title_overlay_path(temp_dir, input_file.stem)
            if not title_overlay_candidate.is_file():
                raise RuntimeError(f"Missing prepared title overlay: {title_overlay_candidate}")
            title_overlay_path = title_overlay_candidate

    if enable_logo_overlay and DEFAULT_LOGO_PATH.is_file():
        target_width_px = _resolve_logo_target_width(input_file)
        logo_target_path = _get_prescaled_logo_path(
            temp_dir=temp_dir,
            target_width_px=target_width_px,
        )
        if not logo_target_path.is_file():
            raise RuntimeError(f"Missing prepared logo overlay: {logo_target_path}")
        logo_path_resolved = logo_target_path
        use_logo = True

    return (title_overlay_path, logo_path_resolved, banner_top, use_logo)


def prepare_video_overlays(
    input_file: Path,
    temp_dir: Path,
    title_path: Path | None,
    title_font: str | None,
    enable_title_overlay: bool,
    enable_logo_overlay: bool,
    title_y_fraction: float | None,
    title_height_fraction: float | None,
) -> tuple[Path | None, Path | None, int | None, bool]:
    """Generate title overlay PNG and pre-scale logo. Returns (title_overlay_path, logo_path, banner_top, use_logo)."""
    title_overlay_path, banner_top = prepare_title_overlay(
        input_file=input_file,
        temp_dir=temp_dir,
        title_path=title_path,
        title_font=title_font,
        enable_title_overlay=enable_title_overlay,
        title_y_fraction=title_y_fraction,
        title_height_fraction=title_height_fraction,
    )
    logo_path_resolved, use_logo = prepare_logo_overlay(
        input_file=input_file,
        temp_dir=temp_dir,
        enable_logo_overlay=enable_logo_overlay,
    )
    return (title_overlay_path, logo_path_resolved, banner_top, use_logo)


def trim_single_video(
    input_file: Path,
    output_dir: Path,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    target_length: Optional[float],
    output_basename: Optional[str] = None,
    encoder: str = "libx265",
    title_path: Path | None = None,
    title_font: str | None = None,
    enable_title_overlay: bool = False,
    enable_logo_overlay: bool = False,
    title_y_fraction: float | None = None,
    title_height_fraction: float | None = None,
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

    use_logo = enable_logo_overlay and DEFAULT_LOGO_PATH.is_file()
    logo_path_resolved = DEFAULT_LOGO_PATH if use_logo else None

    encoder = encoder or get_encoder_config("X265")["codec"]
    use_qsv_hardware_path = encoder == "hevc_qsv"

    (
        title_overlay_path,
        logo_path_resolved,
        banner_top,
        use_logo,
    ) = resolve_prepared_video_overlays(
        input_file=input_file,
        temp_dir=temp_dir_resolved,
        title_path=title_path,
        enable_title_overlay=enable_title_overlay,
        enable_logo_overlay=enable_logo_overlay,
        title_y_fraction=title_y_fraction,
        title_height_fraction=title_height_fraction,
        )

    if artifact.final_strategy == "copy" and title_overlay_path is None and not use_logo:
        copied_output_file = _copy_input_video(
            input_file=input_file,
            output_file=output_file,
            temp_dir=temp_dir_resolved,
            basename=basename,
        )
        wait_for_file_release(copied_output_file)
        return copied_output_file

    def _overlay_wrapped_script_path() -> Path:
        if title_overlay_path is None and not use_logo:
            return artifact.script_path
        if artifact.final_strategy == "minimal":
            raise RuntimeError(
                "Minimal trim fallback cannot be combined with title/logo overlays yet. "
                "This usually means the trim plan kept nothing. "
                "Disable overlays for this file or filter out empty-keep videos before Phase 7."
            )
        if "[outv][outa]" not in artifact.filter_graph:
            raise RuntimeError(f"Trim script does not expose [outv][outa]: {trim_script_path}")
        base_graph = artifact.filter_graph.replace("[outv][outa]", "[basev][outa]", 1)
        overlay_graph = base_graph + _build_overlay_suffix_from_base(
            title_overlay_y=banner_top if title_overlay_path is not None else None,
            logo_enabled=use_logo,
            logo_margin_px=LOGO_OVERLAY_MARGIN_PX,
            logo_alpha=LOGO_OVERLAY_ALPHA,
        )
        scripts_dir = temp_dir_resolved / SCRIPTS_DIR
        scripts_dir.mkdir(parents=True, exist_ok=True)
        combined_script_path = scripts_dir / f"{basename}_final_overlay.ffscript"
        return write_filter_graph_script(combined_script_path, overlay_graph)

    def _run_final_encode(*, use_hw_path: bool) -> Path:
        processing_output = get_processing_video_path(temp_dir_resolved, basename)
        processing_output.parent.mkdir(parents=True, exist_ok=True)
        final_filter_script_path = _overlay_wrapped_script_path()

        def _build_ffmpeg_command(in_file, out_file, filter_script):
            return build_final_trim_command(
                input_file=in_file,
                output_file=processing_output,
                filter_script_path=filter_script,
                encoder=encoder,
                title_overlay_path=title_overlay_path,
                title_overlay_y=banner_top,
                logo_path=logo_path_resolved if use_logo else None,
                source_metadata_filename=(
                    in_file.name if (title_overlay_path is not None or use_logo) else None
                ),
                use_qsv_hardware_path=use_hw_path,
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
