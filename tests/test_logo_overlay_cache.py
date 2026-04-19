"""Tests for logo overlay cache warming and lazy preparation."""

from __future__ import annotations

from pathlib import Path

from src.media import trim


def test_logo_overlay_cache_warm_uses_cached_identity_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_logo = tmp_path / "logo.png"
    source_logo.write_bytes(b"logo")

    monkeypatch.setattr(trim, "DEFAULT_LOGO_PATH", source_logo)
    monkeypatch.setattr(
        trim,
        "probe_video_dimensions",
        lambda _path: (_ for _ in ()).throw(AssertionError("unexpected probe")),
    )

    cache_path = trim._get_prescaled_logo_path(
        tmp_path,
        source_logo_path=source_logo,
        target_width_px=1080,
    )
    cache_path.write_bytes(b"cached")

    assert trim.is_logo_overlay_cache_warm(tmp_path, enable_logo_overlay=True) is True


def test_prepare_logo_overlay_validates_source_logo_once_per_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_logo = tmp_path / "logo.png"
    source_logo.write_bytes(b"logo")

    probe_calls: list[Path] = []
    decode_calls: list[Path] = []

    monkeypatch.setattr(trim, "DEFAULT_LOGO_PATH", source_logo)
    monkeypatch.setattr(trim, "_VALIDATED_SOURCE_LOGO_IDENTITIES", set())
    monkeypatch.setattr(
        trim,
        "probe_video_dimensions",
        lambda path: probe_calls.append(path) or (1080, 1920),
    )
    monkeypatch.setattr(
        trim,
        "probe_ffmpeg_can_decode_image_frame",
        lambda path: decode_calls.append(path),
    )
    monkeypatch.setattr(trim, "_resolve_logo_target_width", lambda _input: 1080)
    monkeypatch.setattr(
        trim,
        "_ensure_prescaled_logo",
        lambda *, source_logo_path, output_logo_path, target_width_px: output_logo_path,
    )

    first_path, first_enabled = trim.prepare_logo_overlay(
        input_file=tmp_path / "a.mkv",
        temp_dir=tmp_path,
        enable_logo_overlay=True,
    )
    second_path, second_enabled = trim.prepare_logo_overlay(
        input_file=tmp_path / "b.mkv",
        temp_dir=tmp_path,
        enable_logo_overlay=True,
    )

    assert first_enabled is True
    assert second_enabled is True
    assert first_path == second_path
    assert probe_calls == [source_logo]
    assert decode_calls == [source_logo]


def test_resolve_prepared_video_overlays_prepares_missing_logo_on_demand(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source_logo = tmp_path / "logo.png"
    source_logo.write_bytes(b"logo")
    prepared_logo = tmp_path / "logo_overlays" / "prepared.png"
    prepared_logo.parent.mkdir(parents=True, exist_ok=True)

    calls: list[tuple[Path, Path, bool]] = []

    monkeypatch.setattr(trim, "DEFAULT_LOGO_PATH", source_logo)
    monkeypatch.setattr(
        trim,
        "prepare_logo_overlay",
        lambda *, input_file, temp_dir, enable_logo_overlay: (
            calls.append((input_file, temp_dir, enable_logo_overlay)) or prepared_logo,
            True,
        ),
    )

    title_overlay_path, logo_path, banner_top, use_logo = trim.resolve_prepared_video_overlays(
        input_file=tmp_path / "video.mkv",
        temp_dir=tmp_path,
        title_path=None,
        enable_title_overlay=False,
        enable_logo_overlay=True,
        title_y_fraction=None,
        title_height_fraction=None,
    )

    assert title_overlay_path is None
    assert logo_path == prepared_logo
    assert banner_top is None
    assert use_logo is True
    assert calls == [(tmp_path / "video.mkv", tmp_path, True)]
