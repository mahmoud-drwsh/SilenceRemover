"""Safety and duration contracts, including real FFmpeg A/V concat verification."""

import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import wave

import pytest

from sr_trim_plan.pause_budget import (
    PausePolicy, TargetDurationUnreachable, allocate_pause_budget,
)
from sr_trim_plan import api
from src.media import trim


def test_short_gaps_untouched_and_long_gaps_capped_even_below_target():
    plan = allocate_pause_budget(20, [2, 5, 10], [2.1, 5.3, 15], 180)
    assert plan.retained_gaps_sec == [0.1, 0.3, 1.2]
    assert plan.segments == [(0, 10.6), (14.4, 20)]
    assert plan.resulting_length_sec == pytest.approx(16.2)


def test_budget_removes_only_needed_slack_and_preserves_pause_variation():
    # 7.2 seconds protected, 1.2 minimum pauses. 9s budget -> 0.6s slack.
    plan = allocate_pause_budget(10, [1, 4], [1.8, 6], 9.5)
    assert plan.resulting_length_sec == 9
    assert plan.retained_gaps_sec == [0.75, 1.05]
    assert plan.minimum_length_sec == 8.4
    # Keep sound adjacent to BOTH speech boundaries, not just before the next word.
    assert plan.segments == [(0, 1.375), (1.425, 4.525), (5.475, 10)]


def test_leading_and_trailing_silence_keep_speech_adjacent_buffer():
    plan = allocate_pause_budget(10, [0, 7], [2, 10], 8)
    assert plan.segments == [(1.8, 7.2)]
    assert plan.resulting_length_sec == 5.4


def test_infeasible_reports_floor_without_returning_over_target_plan():
    with pytest.raises(TargetDurationUnreachable) as error:
        allocate_pause_budget(190, [10], [15], 180)
    assert error.value.minimum_sec == 185.6
    assert error.value.budget_sec == 179.5


@pytest.mark.parametrize("target", [0, -1, float("nan"), float("inf"), 0.5])
def test_invalid_target_is_rejected(target):
    with pytest.raises(ValueError):
        allocate_pause_budget(10, [], [], target)


@pytest.mark.parametrize("starts,ends", [([2, 1], [3, 2]), ([1, 2], [3, 4]),
    ([1], []), ([-1], [2]), ([1], [11]), ([float("nan")], [2]), ([0], [10])])
def test_malformed_or_all_silent_input_is_not_edit_permission(starts, ends):
    with pytest.raises(ValueError):
        allocate_pause_budget(10, starts, ends, 20)


def test_adjacent_intervals_form_one_pause():
    assert allocate_pause_budget(10, [1, 2], [2, 3], 20) == allocate_pause_budget(10, [1], [3], 20)


def test_randomized_budget_invariants():
    rng = random.Random(2381)
    for _ in range(300):
        starts, ends = [], []
        cursor = 0.0
        for _ in range(rng.randint(1, 80)):
            cursor += rng.uniform(0.1, 3)
            starts.append(round(cursor, 6))
            cursor += rng.uniform(0.01, 5)
            ends.append(round(cursor, 6))
        duration = round(cursor + 1, 6)
        capped = allocate_pause_budget(duration, starts, ends, duration + 1)
        target = capped.minimum_length_sec + 0.5 + rng.uniform(0.001, 2)
        plan = allocate_pause_budget(duration, starts, ends, target)
        assert plan.resulting_length_sec < target
        assert sum(b-a for a,b in plan.segments) == pytest.approx(plan.resulting_length_sec, abs=1e-6)
        for a, b, retained in zip(starts, ends, plan.retained_gaps_sec):
            assert retained >= min(b-a, 0.6) - 1e-6
            assert retained <= min(b-a, 1.2) + 1e-6
            # Every discarded interval stays entirely inside detected silence.
        for (_, cut_start), (cut_end, _) in zip(plan.segments, plan.segments[1:]):
            assert any(a <= cut_start <= cut_end <= b for a, b in zip(starts, ends))


def test_planner_detects_once_at_fixed_threshold_and_propagates_failure(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(api, "probe_duration", lambda _: 10)
    def detect(**kwargs):
        calls.append(kwargs)
        return [2], [6]
    monkeypatch.setattr(api, "detect_silence", detect)
    plan = api.build_trim_plan(tmp_path / "x.mp4", 8, -12, 0.01, 0)
    assert len(calls) == 1 and calls[0]["noise_threshold"] == -50
    assert plan.resulting_length_sec == 7.2
    def failure(**kwargs):
        raise RuntimeError("detection failed")
    monkeypatch.setattr(api, "detect_silence", failure)
    with pytest.raises(RuntimeError, match="detection failed"):
        api.build_trim_plan(tmp_path / "x.mp4", 8, -12, 0.01, 0)


@pytest.mark.parametrize("duration", [180, 180.01, float("nan"), 0])
def test_final_duration_gate_is_strict(monkeypatch, duration):
    monkeypatch.setattr(trim, "probe_duration", lambda _: duration)
    with pytest.raises(ValueError, match="does not satisfy"):
        trim.validate_target_duration(Path("output.mp4"), 180)


def test_overlong_encode_is_not_promoted_to_final(monkeypatch, tmp_path):
    from src.ffmpeg.trim_script_bundle import TrimScriptArtifact
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    script = tmp_path / "trim.ffscript"
    artifact = TrimScriptArtifact(script, "concat", "[outv][outa]")
    monkeypatch.setattr(trim, "load_trim_script", lambda *a, **kw: artifact)
    monkeypatch.setattr(trim, "resolve_prepared_video_overlays", lambda **kw: (None, None, 0, False))
    monkeypatch.setattr(trim, "probe_duration", lambda _: 180.04)
    def encode(**kwargs):
        kwargs["output_file"].write_bytes(b"overlong")
    monkeypatch.setattr(trim, "run_silence_removed_media_with_script", encode)
    with pytest.raises(ValueError, match="does not satisfy"):
        trim.trim_single_video(source, tmp_path / "final", -50, 0.6, 0.3, 180,
                               trim_script_path=script)
    assert not (tmp_path / "final" / "source.mp4").exists()


def test_target_script_cache_includes_algorithm_version(monkeypatch, tmp_path):
    from src.ffmpeg import trim_script_bundle as bundle
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    args = dict(input_file=source, temp_dir=tmp_path, target_length=180,
                noise_threshold=-50, min_duration=0.6, pad_sec=0.3)
    old = bundle.get_trim_script_path(**args)
    monkeypatch.setattr(bundle, "NATURAL_PAUSE_POLICY_VERSION", "future-policy")
    assert bundle.get_trim_script_path(**args) != old


def test_real_ffmpeg_keeps_quiet_material_and_produces_under_three_minutes(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe required")
    # Synthetic tones verify mechanics, NOT speech naturalness. -42dB tone
    # would be endangered by the previous -35dB detector search.
    rate = 16000
    audio = tmp_path / "source.wav"
    with wave.open(str(audio), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        tone = b"".join(struct.pack("<h", round(260 * math.sin(2*math.pi*440*i/rate)))
                        for i in range(rate))
        for second in range(186):
            out.writeframes(bytes(rate*2) if 30 <= second < 35 or 90 <= second < 95 else tone)
    plan = api.build_trim_plan(audio, 180, -35, 0.01, 0)
    assert plan.resulting_length_sec == pytest.approx(178.4, abs=0.03)
    assert plan.segments_to_keep[0][1] >= 30
    assert plan.segments_to_keep[-1][0] <= 95
    from sr_filter_graph import build_video_audio_concat_filter_graph
    source = tmp_path / "source.mkv"
    def run(args):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       check=True, capture_output=True)
    run(["-f", "lavfi", "-i", "color=s=32x32:r=25:d=186", "-i", str(audio),
         "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-c:a", "pcm_s16le", str(source)])
    output = tmp_path / "edited.mp4"
    graph = build_video_audio_concat_filter_graph(plan.segments_to_keep)
    run(["-i", str(source), "-filter_complex", graph, "-map", "[outv]", "-map", "[outa]",
         "-c:v", "libx264", "-preset", "ultrafast", "-threads", "1", "-c:a", "aac", str(output)])
    trim.validate_target_duration(output, 180)
    assert trim.probe_duration(output) == pytest.approx(plan.resulting_length_sec, abs=0.15)
