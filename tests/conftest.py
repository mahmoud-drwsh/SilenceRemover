"""Pytest configuration and shared fixtures.

Provides fixtures for integration tests that require video files.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "packages"))

# Fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def sample_vertical() -> Path:
    """5-second vertical video (1080x1920) with audio."""
    path = FIXTURES_DIR / "sample_vertical.mp4"
    if not path.exists():
        pytest.skip("Fixture not found. Run: python tests/generate_fixtures.py")
    return path


@pytest.fixture
def sample_with_silence() -> Path:
    """5-second video with silence sections at 1-2s and 3-4s."""
    path = FIXTURES_DIR / "sample_with_silence.mp4"
    if not path.exists():
        pytest.skip("Fixture not found. Run: python tests/generate_fixtures.py")
    return path


@pytest.fixture
def sample_varying_audio() -> Path:
    """5-second video with varying audio levels."""
    path = FIXTURES_DIR / "sample_varying_audio.mp4"
    if not path.exists():
        pytest.skip("Fixture not found. Run: python tests/generate_fixtures.py")
    return path


@pytest.fixture
def sample_no_audio() -> Path:
    """5-second video without audio."""
    path = FIXTURES_DIR / "sample_no_audio.mp4"
    if not path.exists():
        pytest.skip("Fixture not found. Run: python tests/generate_fixtures.py")
    return path


@pytest.fixture
def sample_short() -> Path:
    """2-second short video with audio (for quick tests)."""
    path = FIXTURES_DIR / "sample_short.mp4"
    if not path.exists():
        pytest.skip("Fixture not found. Run: python tests/generate_fixtures.py")
    return path


@pytest.fixture
def sample_horizontal() -> Path:
    """5-second horizontal video (1920x1080) with audio."""
    path = FIXTURES_DIR / "sample_horizontal.mp4"
    if not path.exists():
        pytest.skip("Fixture not found. Run: python tests/generate_fixtures.py")
    return path


@pytest.fixture
def any_video(sample_vertical) -> Path:
    """Default to sample_vertical for generic video tests."""
    return sample_vertical
