import pytest

from sr_subtitles.api import _group_segments, render_srt


def test_render_srt_uses_contiguous_final_timeline() -> None:
    result = render_srt([(2.0, 4.0), (10.0, 11.5)], ["  أهلا   بكم ", "هذا اختبار"])
    assert "00:00:00,000 --> 00:00:02,000" in result
    assert "00:00:02,000 --> 00:00:03,500" in result
    assert "أهلا بكم" in result


def test_subtitle_groups_preserve_final_duration() -> None:
    groups = _group_segments([(0.0, 0.1)] * 13)
    assert len(groups) == 2
    assert groups[0][2] == pytest.approx(1.2)
    assert groups[1][2] == pytest.approx(0.1)
