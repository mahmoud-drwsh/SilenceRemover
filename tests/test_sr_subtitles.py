import pytest

from sr_subtitles.api import _group_segment_batches, _group_segments, _served_chunks, render_srt, validate_model_srt


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


def test_subtitle_groups_bound_retained_audio_duration() -> None:
    groups = _group_segments([(0.0, 15.0), (16.0, 31.0)])
    assert groups == [(0.0, 15.0, 15.0), (16.0, 31.0, 15.0)]


def test_subtitle_batches_preserve_disjoint_source_ranges() -> None:
    batches = _group_segment_batches([(0.0, 4.0), (100.0, 104.0)])
    assert batches == [[(0.0, 4.0), (100.0, 104.0)]]


def test_served_chunks_prefer_silence_near_target() -> None:
    chunks = _served_chunks(24.0, [7.0, 15.0], [9.0, 17.0])
    assert chunks == [(0.0, 8.0), (8.0, 16.0), (16.0, 24.0)]


def test_served_chunks_fall_back_to_bounded_deterministic_cuts() -> None:
    chunks = _served_chunks(27.0, [], [])
    assert chunks == [(0.0, 8.0), (8.0, 16.0), (16.0, 21.5), (21.5, 27.0)]


def test_model_srt_is_normalized_after_timing_validation() -> None:
    raw = "```srt\n1\n00:00:00,100 --> 00:00:02,000\nمرحبا\n\n2\n00:00:02,100 --> 00:00:04,000\nبكم\n```"
    result = validate_model_srt(raw, 4.0)
    assert result.startswith("1\n00:00:00,100 --> 00:00:02,000")
    assert result.endswith("بكم\n\n")


def test_model_srt_normalizes_gemini_colon_millisecond_dialect() -> None:
    raw = "1\n00:00:01:216 --> 00:05:406\nمرحبا\n\n2\n00:06:56 --> 00:10:86\nبكم"
    result = validate_model_srt(raw, 11.0)
    assert "00:00:01,216 --> 00:00:05,406" in result
    assert "00:00:06,560 --> 00:00:10,860" in result


def test_model_srt_accepts_gemini_minute_timestamps_without_blank_lines() -> None:
    raw = "1\n00:24,800 --> 00:31,520\nمرحبا\n2\n01:02,280 --> 01:07,070\nبكم"
    result = validate_model_srt(raw, 68.0)
    assert "00:00:24,800 --> 00:00:31,520" in result
    assert "00:01:02,280 --> 00:01:07,070" in result


def test_model_srt_clamps_small_model_overlap_deterministically() -> None:
    raw = "1\n00:00:00,000 --> 00:00:02,000\nأول\n2\n00:00:01,800 --> 00:00:03,000\nثان"
    result = validate_model_srt(raw, 3.0)
    assert "00:00:02,000 --> 00:00:03,000" in result


def test_model_srt_rejects_collapsed_embedded_cues() -> None:
    raw = "1\n00:00:00,000 --> 00:00:20,000\nأول 2 00:00:20,000 --> 00:00:30,000 ثان"
    with pytest.raises(RuntimeError, match="embedded cue syntax"):
        validate_model_srt(raw, 30.0)


def test_model_srt_requires_timeline_coverage() -> None:
    raw = "1\n00:00:00,000 --> 00:00:02,000\nأول\n2\n00:00:02,000 --> 00:00:04,000\nثان"
    with pytest.raises(RuntimeError, match="cover enough"):
        validate_model_srt(raw, 30.0)


@pytest.mark.parametrize("raw", [
    "commentary", "1\n00:00:02,000 --> 00:00:01,000\nنص", "2\n00:00:00,000 --> 00:00:01,000\nنص",
])
def test_model_srt_rejects_invalid_contract(raw: str) -> None:
    with pytest.raises(RuntimeError):
        validate_model_srt(raw, 3.0)
