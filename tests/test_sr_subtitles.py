import pytest

from sr_subtitles.api import _parse_texts, render_srt


def test_render_srt_uses_contiguous_final_timeline() -> None:
    result = render_srt([(2.0, 4.0), (10.0, 11.5)], ["  أهلا   بكم ", "هذا اختبار"])
    assert "00:00:00,000 --> 00:00:02,000" in result
    assert "00:00:02,000 --> 00:00:03,500" in result
    assert "أهلا بكم" in result


@pytest.mark.parametrize("raw", ["[]", '["only"]', '["", "ok"]', "not json"])
def test_subtitle_response_is_strictly_guarded(raw: str) -> None:
    with pytest.raises(RuntimeError):
        _parse_texts(raw, 2)
