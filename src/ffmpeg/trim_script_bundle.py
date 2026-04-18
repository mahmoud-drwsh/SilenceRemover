"""Pre-generated trim-script artifacts shared by snippet and final encode phases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.ffmpeg.filter_graph import write_filter_graph_script
from src.ffmpeg.probing import probe_duration, probe_has_audio_stream
from sr_filter_graph import build_audio_concat_filter_graph, build_video_audio_concat_filter_graph
from sr_trim_plan import build_trim_plan
from sr_trim_plan.api import should_copy_when_target_exceeds_input

TRIM_SCRIPTS_DIR = "trim_scripts"
SNIPPET_TRIM_SCRIPT_SUFFIX = ".snippet.ffscript"

FinalStrategy = Literal["concat", "copy", "minimal"]


@dataclass(frozen=True)
class TrimScriptArtifact:
    script_path: Path
    final_strategy: FinalStrategy
    filter_graph: str


def _float_token(value: float | None) -> str:
    if value is None:
        return "none"
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text.replace("-", "m").replace(".", "p")


def _trim_root(temp_dir: Path) -> Path:
    root = temp_dir / TRIM_SCRIPTS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _script_name(
    *,
    input_file: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
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
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    safe_base = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in input_file.stem)[:40] or "video"
    return (
        f"{safe_base}__t-{_float_token(target_length)}__n-{_float_token(noise_threshold)}"
        f"__d-{_float_token(min_duration)}__p-{_float_token(pad_sec)}__sig-{digest}.ffscript"
    )


def get_trim_script_path(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
) -> Path:
    return _trim_root(temp_dir) / _script_name(
        input_file=input_file,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )


def get_snippet_trim_script_path_from_final(final_script_path: Path) -> Path:
    return final_script_path.with_suffix(SNIPPET_TRIM_SCRIPT_SUFFIX)


def get_snippet_trim_script_path(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
) -> Path:
    return get_snippet_trim_script_path_from_final(
        get_trim_script_path(
            input_file=input_file,
            temp_dir=temp_dir,
            target_length=target_length,
            noise_threshold=noise_threshold,
            min_duration=min_duration,
            pad_sec=pad_sec,
        )
    )


def _read_filter_graph(script_path: Path) -> str:
    filter_graph = script_path.read_text(encoding="utf-8").strip()
    if not filter_graph:
        raise RuntimeError(f"Invalid trim script artifact: {script_path}")
    return filter_graph


def _build_silent_audio_chain(label: str, duration_sec: float) -> str:
    return (
        f"anullsrc=channel_layout=stereo:sample_rate=48000,"
        f"atrim=start=0:end={duration_sec},asetpts=PTS-STARTPTS[{label}]"
    )


def _build_final_concat_graph(
    segments_to_keep: list[tuple[float, float]],
    *,
    input_has_audio: bool,
) -> str:
    if input_has_audio:
        return build_video_audio_concat_filter_graph(segments_to_keep)

    filter_chains = "".join(
        (
            f"[0:v]trim=start={segment_start}:end={segment_end},setpts=PTS-STARTPTS[v{i}];"
            f"{_build_silent_audio_chain(f'a{i}', segment_end - segment_start)};"
        )
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(segments_to_keep)))
    return f"{filter_chains}{concat_inputs}concat=n={len(segments_to_keep)}:v=1:a=1[outv][outa]"


def _build_final_minimal_graph(*, input_has_audio: bool) -> str:
    if input_has_audio:
        return (
            "[0:v]trim=start=0:end=0.1,setpts=PTS-STARTPTS[outv];"
            "[0:a]atrim=start=0:end=0.1,asetpts=PTS-STARTPTS[outa]"
        )
    return (
        "[0:v]trim=start=0:end=0.1,setpts=PTS-STARTPTS[outv];"
        f"{_build_silent_audio_chain('outa', 0.1)}"
    )


def _build_audio_only_concat_graph(
    segments_to_keep: list[tuple[float, float]],
    *,
    input_has_audio: bool,
) -> str:
    if input_has_audio:
        return build_audio_concat_filter_graph(segments_to_keep)

    filter_chains = "".join(
        _build_silent_audio_chain(f"a{i}", segment_end - segment_start) + ";"
        for i, (segment_start, segment_end) in enumerate(segments_to_keep)
    )
    concat_inputs = "".join(f"[a{i}]" for i in range(len(segments_to_keep)))
    return f"{filter_chains}{concat_inputs}concat=n={len(segments_to_keep)}:v=0:a=1[outa]"


def _build_audio_only_minimal_graph(*, input_has_audio: bool) -> str:
    if input_has_audio:
        return "[0:a]atrim=start=0:end=0.1,asetpts=PTS-STARTPTS[outa]"
    return _build_silent_audio_chain("outa", 0.1)


def _derive_snippet_filter_graph(final_filter_graph: str) -> str:
    chains = [chain.strip() for chain in final_filter_graph.split(";") if chain.strip()]
    if "concat=n=" not in final_filter_graph:
        audio_chain = next(
            (chain for chain in chains if chain.endswith("[outa]") and "[outv]" not in chain),
            None,
        )
        if audio_chain is None:
            raise RuntimeError("Could not derive snippet trim script from final minimal graph")
        return audio_chain

    audio_chains: list[str] = []
    audio_labels: list[str] = []
    for chain in chains:
        match = re.search(r"\[([^\[\]]+)\]$", chain)
        if match is None:
            continue
        label = match.group(1)
        if re.fullmatch(r"a\d+", label):
            audio_chains.append(chain)
            audio_labels.append(label)

    if not audio_chains:
        raise RuntimeError("Could not derive snippet trim script from final concat graph")

    concat_inputs = "".join(f"[{label}]" for label in audio_labels)
    return f"{';'.join(audio_chains)};{concat_inputs}concat=n={len(audio_labels)}:v=0:a=1[outa]"


def derive_snippet_trim_script(
    final_script_path: Path,
    *,
    snippet_script_path: Path | None = None,
) -> Path:
    final_filter_graph = _read_filter_graph(final_script_path)
    snippet_filter_graph = _derive_snippet_filter_graph(final_filter_graph)
    resolved_path = (
        snippet_script_path
        if snippet_script_path is not None
        else get_snippet_trim_script_path_from_final(final_script_path)
    )
    return write_filter_graph_script(resolved_path, snippet_filter_graph)


def ensure_snippet_trim_script(
    final_script_path: Path,
    *,
    snippet_script_path: Path | None = None,
) -> Path:
    resolved_path = (
        snippet_script_path
        if snippet_script_path is not None
        else get_snippet_trim_script_path_from_final(final_script_path)
    )
    if resolved_path.is_file():
        try:
            _read_filter_graph(resolved_path)
            return resolved_path
        except RuntimeError:
            pass
    return derive_snippet_trim_script(final_script_path, snippet_script_path=resolved_path)


def load_trim_script(
    script_path: Path,
    *,
    input_file: Path | None = None,
    target_length: float | None = None,
) -> TrimScriptArtifact:
    filter_graph = _read_filter_graph(script_path)

    if "concat=n=" in filter_graph:
        if input_file is not None and should_copy_when_target_exceeds_input(
            probe_duration(input_file),
            target_length,
        ):
            final_strategy: FinalStrategy = "copy"
        else:
            final_strategy = "concat"
    else:
        final_strategy = "minimal"

    return TrimScriptArtifact(
        script_path=script_path,
        final_strategy=final_strategy,
        filter_graph=filter_graph,
    )


def is_trim_script_ready(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
) -> bool:
    final_script_path = get_trim_script_path(
        input_file=input_file,
        temp_dir=temp_dir,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )
    snippet_script_path = get_snippet_trim_script_path_from_final(final_script_path)
    if not final_script_path.is_file():
        return False
    try:
        load_trim_script(final_script_path)
        ensure_snippet_trim_script(final_script_path, snippet_script_path=snippet_script_path)
        return True
    except RuntimeError:
        return False


def generate_trim_script(
    *,
    input_file: Path,
    temp_dir: Path,
    target_length: float | None,
    noise_threshold: float,
    min_duration: float,
    pad_sec: float,
) -> Path:
    final_script_path = get_trim_script_path(
        input_file=input_file,
        temp_dir=temp_dir,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
    )
    snippet_script_path = get_snippet_trim_script_path_from_final(final_script_path)

    plan = build_trim_plan(
        input_file=input_file,
        target_length=target_length,
        noise_threshold=noise_threshold,
        min_duration=min_duration,
        pad_sec=pad_sec,
        temp_dir=temp_dir,
    )
    input_has_audio = probe_has_audio_stream(input_file)

    if len(plan.segments_to_keep) == 0:
        final_filter_graph = _build_final_minimal_graph(input_has_audio=input_has_audio)
        snippet_filter_graph = _build_audio_only_minimal_graph(input_has_audio=input_has_audio)
    else:
        final_filter_graph = _build_final_concat_graph(
            plan.segments_to_keep,
            input_has_audio=input_has_audio,
        )
        snippet_filter_graph = _build_audio_only_concat_graph(
            plan.segments_to_keep,
            input_has_audio=input_has_audio,
        )

    write_filter_graph_script(final_script_path, final_filter_graph)
    write_filter_graph_script(snippet_script_path, snippet_filter_graph)
    return final_script_path


__all__ = [
    "TRIM_SCRIPTS_DIR",
    "SNIPPET_TRIM_SCRIPT_SUFFIX",
    "TrimScriptArtifact",
    "derive_snippet_trim_script",
    "ensure_snippet_trim_script",
    "generate_trim_script",
    "get_snippet_trim_script_path",
    "get_snippet_trim_script_path_from_final",
    "get_trim_script_path",
    "is_trim_script_ready",
    "load_trim_script",
]
