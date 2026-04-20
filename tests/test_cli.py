"""CLI and startup wiring tests."""

import sys
from argparse import Namespace
from types import SimpleNamespace

import pytest

from src.core import cli
from src.startup import bootstrap


def _parse_args_with(monkeypatch, args: list[str]):
    monkeypatch.setattr(sys, "argv", ["main.py"] + args, raising=False)
    return cli.parse_args()


def test_parse_args_accepts_non_target_names(monkeypatch, tmp_path):
    parsed = _parse_args_with(
        monkeypatch,
        [
            str(tmp_path),
            "--non-target-noise-threshold",
            "-40",
            "--non-target-min-duration",
            "1.1",
            "--non-target-pad-sec",
            "0.5",
        ],
    )

    assert parsed.non_target_noise_threshold == -40.0
    assert parsed.non_target_min_duration == 1.1
    assert parsed.non_target_pad_sec == 0.5


@pytest.mark.parametrize(
    "flag, value",
    [
        ("--noise-threshold", "-40"),
        ("--min-duration", "1.0"),
        ("--pad-sec", "0.5"),
    ],
)
def test_parse_args_rejects_legacy_names(monkeypatch, tmp_path, flag, value):
    with pytest.raises(SystemExit):
        _parse_args_with(monkeypatch, [str(tmp_path), flag, value])


def test_startup_context_reads_non_target_trim_flags(monkeypatch, tmp_path):
    captured = {}

    def fake_resolve_trim_defaults(
        *, target_length, noise_threshold, min_duration, pad_sec=None
    ):
        captured.update(
            target_length=target_length,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
        )
        return SimpleNamespace(
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
        )

    input_dir = tmp_path / "videos"
    input_dir.mkdir()
    fake_inputs = [tmp_path / "sample.mp4"]

    monkeypatch.setattr(bootstrap, "require_tools", lambda *_tools: None)
    monkeypatch.setattr(bootstrap, "require_input_dir", lambda _path: None)
    monkeypatch.setattr(bootstrap, "load_config", lambda: {"OPENROUTER_API_KEY": "x"})
    monkeypatch.setattr(bootstrap, "get_config", lambda: {"OPENROUTER_API_KEY": "x"})
    monkeypatch.setattr(bootstrap, "collect_video_files", lambda _input_dir: fake_inputs)
    monkeypatch.setattr(bootstrap, "resolve_trim_defaults", fake_resolve_trim_defaults)

    context = bootstrap.build_startup_context(
        Namespace(
            input_dir=str(input_dir),
            target_length=None,
            non_target_noise_threshold=-44.0,
            non_target_min_duration=1.7,
            non_target_pad_sec=0.8,
            title_font="Noto Naskh Arabic",
            enable_title_overlay=False,
            enable_logo_overlay=False,
        )
    )

    assert context.noise_threshold == -44.0
    assert context.min_duration == 1.7
    assert context.pad_sec == 0.8
    assert captured["noise_threshold"] == -44.0
    assert captured["min_duration"] == 1.7
    assert captured["pad_sec"] == 0.8
    assert captured["target_length"] is None
