import pytest

from scripts.normalize_subtitle_cues import Cue, normalize_srt, parse_srt, render_srt, split_cue


def test_short_cue_is_unchanged() -> None:
    cue = Cue(0.0, 8.0, "مرحبا بكم")
    assert split_cue(cue) == [cue]


def test_long_arabic_cue_is_split_and_preserves_text_and_timeline() -> None:
    text = " ".join(f"كلمة{i}" for i in range(90))
    parts = split_cue(Cue(2.0, 32.0, text))
    assert parts[0].start == 2.0
    assert parts[-1].end == 32.0
    assert " ".join(part.text for part in parts) == text
    assert all(part.end - part.start <= 10.0 for part in parts)
    assert all(left.end == pytest.approx(right.start) for left, right in zip(parts, parts[1:]))


def test_oversized_payload_is_split_even_when_duration_is_short() -> None:
    cue = Cue(0.0, 8.0, " ".join(["العربية"] * 300))
    parts = split_cue(cue)
    assert len(parts) > 1
    assert all(len(part.text.encode("utf-8")) <= 1_800 for part in parts)


def test_normalization_is_idempotent_and_sequential() -> None:
    raw = "1\n00:00:00,000 --> 00:00:25,000\nأهلا بكم في هذا الاختبار الطويل جدا والمتكرر مرات كثيرة اليوم\n\n"
    once = normalize_srt(raw)
    assert normalize_srt(once) == once
    cues = parse_srt(once)
    assert len(cues) == 4
    assert render_srt(cues) == once


@pytest.mark.parametrize("raw", [
    "", "2\n00:00:00,000 --> 00:00:01,000\nنص\n", "1\ninvalid\nنص\n",
    "1\n00:00:02,000 --> 00:00:01,000\nنص\n",
])
def test_invalid_srt_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_srt(raw)
