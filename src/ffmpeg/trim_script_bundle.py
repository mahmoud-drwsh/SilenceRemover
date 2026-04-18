"""Pre-generated trim-script bundles shared by snippet and final encode phases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.core.constants import (
    DEFAULT_LOGO_PATH,
    TITLE_BANNER_START_FRACTION,
)
from src.ffmpeg.filter_graph import write_filter_graph_script
from src.ffmpeg.probing import probe_has_audio_stream, probe_video_dimensions
from sr_filter_graph import (
    build_audio_concat_filter_graph,
    build_minimal_encode_overlay_filter_complex,
    build_video_audio_concat_filter_graph,
    build_video_audio_concat_filter_graph_with_title_overlay,
    build_video_lavfi_audio_concat_filter_graph,
    build_video_lavfi_audio_concat_filter_graph_with_title_overlay,
)
from sr_trim_plan import build_trim_plan

TRIM_SCRIPT_BUNDLES_DIR = "trim_script_bundles"

SnippetStrategy = Literal["concat", "minimal", "silent"]
FinalStrategy = Literal["concat", "concat_lavfi", "copy", "minimal", "minimal_overlay"]


@dataclass(frozen=True)
class TrimScriptBundle:
    bundle_dir: Path
    snippet_strategy: SnippetStrategy
    snippet_script_path: Path | None
    final_strategy: FinalStrategy
    final_script_path: Path | None
    expected_total_seconds: float | None


def _float_token(value: float | None) -> str:
    if value is None:
        return "none"
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text.replace("-", "m").replace(".", "p")


def _float_from_token(token: str) -> float:
    return float(token.replace("m", "-").replace("p", "."))


def _bundle_dir_name(
    *,
    input_file: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    title_overlay_enabled: bool,
    title_y_fraction: float | None,
    logo_overlay_enabled: bool,
) -> str:
    stat = input_file.stat()
    payload = {
        "basename": input_file.stem,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "inode": getattr(stat, "st_ino", 0),
        "target_length": target_length,
        "noise_threshold": noise_threshold,
        "min_duration": min_duration,
        "pad_sec": pad_sec,
        "title_overlay_enabled": title_overlay_enabled,
        "title_y_fraction": title_y_fraction,
        "logo_overlay_enabled": logo_overlay_enabled,
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    safe_base = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in input_file.stem)[:40] or "video"
    target_token = _float_token(target_length)
    noise_token = _float_token(noise_threshold)
    min_token = _float_token(min_duration)
    pad_token = _float_token(pad_sec)
    title_token = "1" if title_overlay_enabled else "0"
    logo_token = "1" if logo_overlay_enabled else "0"
    y_token = _float_token(title_y_fraction)
    return (
        f"{safe_base}__t-{target_token}__n-{noise_token}__d-{min_token}__p-{pad_token}"
        f"__to-{title_token}__ty-{y_token}__lo-{logo_token}__sig-{digest}"
    )


def _bundle_root(temp_dir: Path) -> Path:
    root = temp_dir / TRIM_SCRIPT_BUNDLES_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_trim_script_bundle_dir(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    title_overlay_enabled: bool,
    title_y_fraction: float | None,
    logo_overlay_enabled: bool,
) -> Path:
    return _bundle_root(temp_dir) / _bundle_dir_name(
        input_file=input_file,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
        title_overlay_enabled=title_overlay_enabled,
        title_y_fraction=title_y_fraction,
        logo_overlay_enabled=logo_overlay_enabled,
    )


def _load_strategy_file(
    bundle_dir: Path,
    stem_prefix: str,
    suffixes: tuple[str, ...],
) -> Path | None:
    for suffix in suffixes:
        candidate = bundle_dir / f"{stem_prefix}{suffix}"
        if candidate.exists():
            return candidate
    return None


def load_trim_script_bundle(bundle_dir: Path) -> TrimScriptBundle:
    snippet_concat = next(bundle_dir.glob("snippet.concat.len-*.ffscript"), None)
    snippet_minimal = bundle_dir / "snippet.minimal"
    snippet_silent = bundle_dir / "snippet.silent"

    if snippet_concat is not None:
        snippet_strategy: SnippetStrategy = "concat"
        snippet_script_path = snippet_concat
    elif snippet_minimal.exists():
        snippet_strategy = "minimal"
        snippet_script_path = None
    elif snippet_silent.exists():
        snippet_strategy = "silent"
        snippet_script_path = None
    else:
        raise RuntimeError(f"Missing snippet trim artifact in {bundle_dir}")

    final_concat = next(bundle_dir.glob("final.concat.len-*.ffscript"), None)
    final_concat_lavfi = next(bundle_dir.glob("final.concat.lavfi.len-*.ffscript"), None)
    final_copy = bundle_dir / "final.copy"
    final_minimal_overlay = bundle_dir / "final.minimal.overlay.ffscript"
    final_minimal = bundle_dir / "final.minimal"

    expected_total_seconds: float | None = None
    final_strategy: FinalStrategy
    final_script_path: Path | None

    if final_concat is not None:
        final_strategy = "concat"
        final_script_path = final_concat
        expected_total_seconds = _float_from_token(final_concat.stem.split("len-")[-1])
    elif final_concat_lavfi is not None:
        final_strategy = "concat_lavfi"
        final_script_path = final_concat_lavfi
        expected_total_seconds = _float_from_token(final_concat_lavfi.stem.split("len-")[-1])
    elif final_copy.exists():
        final_strategy = "copy"
        final_script_path = None
    elif final_minimal_overlay.exists():
        final_strategy = "minimal_overlay"
        final_script_path = final_minimal_overlay
    elif final_minimal.exists():
        final_strategy = "minimal"
        final_script_path = None
    else:
        raise RuntimeError(f"Missing final trim artifact in {bundle_dir}")

    return TrimScriptBundle(
        bundle_dir=bundle_dir,
        snippet_strategy=snippet_strategy,
        snippet_script_path=snippet_script_path,
        final_strategy=final_strategy,
        final_script_path=final_script_path,
        expected_total_seconds=expected_total_seconds,
    )


def is_trim_script_bundle_ready(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    title_overlay_enabled: bool,
    title_y_fraction: float | None,
    logo_overlay_enabled: bool,
) -> bool:
    bundle_dir = get_trim_script_bundle_dir(
        input_file=input_file,
        temp_dir=temp_dir,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
        title_overlay_enabled=title_overlay_enabled,
        title_y_fraction=title_y_fraction,
        logo_overlay_enabled=logo_overlay_enabled,
    )
    if not bundle_dir.is_dir():
        return False
    try:
        load_trim_script_bundle(bundle_dir)
        return True
    except RuntimeError:
        return False


def _write_marker(path: Path) -> None:
    path.write_text("", encoding="utf-8")


def _resolve_title_overlay_y(
    input_file: Path,
    *,
    title_overlay_enabled: bool,
    title_y_fraction: float | None,
) -> int | None:
    if not title_overlay_enabled:
        return None
    _video_width, video_height = probe_video_dimensions(input_file)
    effective_start_fraction = (
        title_y_fraction if title_y_fraction is not None else TITLE_BANNER_START_FRACTION
    )
    return int(video_height * effective_start_fraction)


def generate_trim_script_bundle(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
    title_overlay_enabled: bool,
    title_y_fraction: float | None,
    logo_overlay_enabled: bool,
) -> Path:
    effective_logo_overlay = bool(logo_overlay_enabled and DEFAULT_LOGO_PATH.is_file())
    bundle_dir = get_trim_script_bundle_dir(
        input_file=input_file,
        temp_dir=temp_dir,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
        title_overlay_enabled=title_overlay_enabled,
        title_y_fraction=title_y_fraction,
        logo_overlay_enabled=effective_logo_overlay,
    )
    bundle_dir.mkdir(parents=True, exist_ok=True)

    for existing in bundle_dir.iterdir():
        if existing.is_file():
            existing.unlink()

    plan = build_trim_plan(
        input_file=input_file,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
        temp_dir=temp_dir,
    )
    input_has_audio = probe_has_audio_stream(input_file)
    segments_to_keep = plan.segments_to_keep
    overlay_y = _resolve_title_overlay_y(
        input_file,
        title_overlay_enabled=title_overlay_enabled,
        title_y_fraction=title_y_fraction,
    )
    burn_in = bool(title_overlay_enabled or effective_logo_overlay)

    if not input_has_audio:
        _write_marker(bundle_dir / "snippet.silent")
    elif len(segments_to_keep) == 0:
        _write_marker(bundle_dir / "snippet.minimal")
    else:
        snippet_path = bundle_dir / f"snippet.concat.len-{_float_token(plan.resulting_length_sec)}.ffscript"
        write_filter_graph_script(snippet_path, build_audio_concat_filter_graph(segments_to_keep))

    if plan.should_copy_input and not burn_in:
        _write_marker(bundle_dir / "final.copy")
        return bundle_dir

    if len(segments_to_keep) == 0:
        if burn_in:
            final_path = bundle_dir / "final.minimal.overlay.ffscript"
            write_filter_graph_script(
                final_path,
                build_minimal_encode_overlay_filter_complex(
                    title_overlay_y=overlay_y,
                    logo_enabled=effective_logo_overlay,
                ),
            )
        else:
            _write_marker(bundle_dir / "final.minimal")
        return bundle_dir

    if burn_in:
        if input_has_audio:
            final_graph = build_video_audio_concat_filter_graph_with_title_overlay(
                segments_to_keep,
                overlay_y,
                logo_enabled=effective_logo_overlay,
            )
            final_name = f"final.concat.len-{_float_token(plan.resulting_length_sec)}.ffscript"
        else:
            final_graph = build_video_lavfi_audio_concat_filter_graph_with_title_overlay(
                segments_to_keep,
                overlay_y,
                logo_enabled=effective_logo_overlay,
            )
            final_name = f"final.concat.lavfi.len-{_float_token(plan.resulting_length_sec)}.ffscript"
    else:
        if input_has_audio:
            final_graph = build_video_audio_concat_filter_graph(segments_to_keep)
            final_name = f"final.concat.len-{_float_token(plan.resulting_length_sec)}.ffscript"
        else:
            final_graph = build_video_lavfi_audio_concat_filter_graph(segments_to_keep)
            final_name = f"final.concat.lavfi.len-{_float_token(plan.resulting_length_sec)}.ffscript"

    write_filter_graph_script(bundle_dir / final_name, final_graph)
    return bundle_dir


__all__ = [
    "TRIM_SCRIPT_BUNDLES_DIR",
    "TrimScriptBundle",
    "generate_trim_script_bundle",
    "get_trim_script_bundle_dir",
    "is_trim_script_bundle_ready",
    "load_trim_script_bundle",
]
