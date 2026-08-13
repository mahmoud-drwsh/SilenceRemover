from __future__ import annotations

from pathlib import Path


def test_vertical_launcher_does_not_pass_removed_media_manager_flag() -> None:
    launcher = (
        Path(__file__).resolve().parents[1]
        / "pwsh"
        / "Start-VerticalVideoProcessing.ps1"
    )

    assert '"--enable-media-manager"' not in launcher.read_text(encoding="utf-8")


def test_only_vertical_launcher_inherits_media_manager_upload_configuration() -> None:
    horizontal = (
        Path(__file__).resolve().parents[1]
        / "pwsh"
        / "Start-HorizontalVideoProcessing.ps1"
    ).read_text(encoding="utf-8")

    assert "Remove-Item Env:MEDIA_MANAGER_URL" in horizontal
    assert "$env:MEDIA_MANAGER_URL = $previousMediaManagerUrl" in horizontal
