"""A small, lease-fenced worker for server-owned source recordings.

This module deliberately stops after the deterministic trim plan.  It proves
the worker control/data-plane boundary without invoking OpenRouter or encoding
derived media, and has no dependency on the client-owned pipeline runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import quote

import httpx

from src.core.constants import (
    NON_TARGET_MIN_DURATION_SEC,
    NON_TARGET_NOISE_THRESHOLD_DB,
    NON_TARGET_PAD_SEC,
)
from sr_trim_plan import TrimPlan, build_trim_plan
from sr_trim_plan.pause_budget import NATURAL_PAUSE_POLICY_VERSION, PausePolicy
from src.media.trim import validate_target_duration
from sr_filter_graph import build_audio_concat_filter_graph
from sr_source_processing.review_analysis import ReviewAnalysisError, analyze_review_ogg
from sr_subtitles import generate_srt_from_trim_segments, mux_srt_track
from src.ffmpeg.trim_script_bundle import write_trim_script_from_plan
from src.media.trim import prepare_video_overlays, trim_single_video


class WorkerError(RuntimeError):
    """An actionable worker control- or data-plane failure."""


@dataclass(frozen=True)
class WorkerConfig:
    """Non-client configuration for one server-owned processing project."""

    service_url: str
    project: str
    worker_token: str
    work_dir: Path
    heartbeat_interval_sec: float = 30.0
    request_timeout_sec: float = 60.0
    target_length: float | None = None
    noise_threshold: float = NON_TARGET_NOISE_THRESHOLD_DB
    min_duration: float = NON_TARGET_MIN_DURATION_SEC
    pad_sec: float = NON_TARGET_PAD_SEC
    openrouter_api_key: str | None = None
    encoder: str = "X265"
    enable_title_overlay: bool = False
    enable_logo_overlay: bool = False
    title_font: str | None = None

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        """Read a one-shot worker configuration without changing client config."""
        service_url = os.environ.get("SOURCE_PROCESSING_SERVICE_URL", "").rstrip("/")
        project = os.environ.get("SOURCE_PROCESSING_PROJECT", "").strip()
        token = os.environ.get("SOURCE_PROCESSING_WORKER_TOKEN", "")
        work_dir = os.environ.get("SOURCE_PROCESSING_WORK_DIR", "")
        if not service_url or not project or not token or not work_dir:
            raise WorkerError(
                "SOURCE_PROCESSING_SERVICE_URL, SOURCE_PROCESSING_PROJECT, "
                "SOURCE_PROCESSING_WORKER_TOKEN, and SOURCE_PROCESSING_WORK_DIR are required",
            )
        heartbeat = float(os.environ.get("SOURCE_PROCESSING_HEARTBEAT_INTERVAL_SEC", "30"))
        if heartbeat <= 0:
            raise WorkerError("SOURCE_PROCESSING_HEARTBEAT_INTERVAL_SEC must be positive")
        target_text = os.environ.get("SOURCE_PROCESSING_TARGET_LENGTH", "").strip()
        target = float(target_text) if target_text else None
        if target is not None and (not math.isfinite(target) or target <= PausePolicy().render_margin_sec):
            raise WorkerError("SOURCE_PROCESSING_TARGET_LENGTH must exceed the render margin")
        return cls(
            service_url, project, token, Path(work_dir), heartbeat,
            target_length=target,
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
            encoder=os.environ.get("SOURCE_PROCESSING_ENCODER", "X265"),
            enable_title_overlay=os.environ.get("SOURCE_PROCESSING_ENABLE_TITLE_OVERLAY", "false").lower() == "true",
            enable_logo_overlay=os.environ.get("SOURCE_PROCESSING_ENABLE_LOGO_OVERLAY", "false").lower() == "true",
            title_font=os.environ.get("SOURCE_PROCESSING_TITLE_FONT") or None,
        )


_SAFE_PATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class SourceProcessingWorker:
    """Claim one source job, checkpoint a trim plan, and finalize the lease."""

    def __init__(
        self,
        config: WorkerConfig,
        *,
        client: httpx.Client | None = None,
        trim_planner: Callable[..., TrimPlan] = build_trim_plan,
        subtitle_generator: Callable[..., None] | None = None,
        review_audio_builder: Callable[[Path, Path, list[tuple[float, float]]], None] | None = None,
    ) -> None:
        self.config = config
        self._client = client or httpx.Client(timeout=config.request_timeout_sec)
        self._owns_client = client is None
        self._trim_planner = trim_planner
        self._subtitle_generator = subtitle_generator or generate_srt_from_trim_segments
        self._review_audio_builder = review_audio_builder or self._create_review_audio

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SourceProcessingWorker":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def run_once(self) -> bool:
        """Process at most one job; return false when the project has no work."""
        claimed = self._post("/claim", {})
        job = claimed.get("job")
        if job is None:
            return False
        if not isinstance(job, dict):
            raise WorkerError("Malformed source-processing claim response")
        try:
            self._process_claimed_job(job)
        except Exception as exc:
            # Best effort only: an expired/stolen lease must not mask the root cause.
            self._fail(job, str(exc))
            if isinstance(exc, WorkerError):
                raise
            raise WorkerError(str(exc)) from exc
        return True

    def _process_claimed_job(self, job: Mapping[str, Any]) -> None:
        job_id, lease_token, download_url = self._job_fields(job)
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        original_path = job_dir / self._safe_original_name(job)
        with self._heartbeat(job_id, lease_token):
            self._download_original(download_url, original_path)
            self._verify_checksum(original_path, str(job.get("original_checksum_sha256", "")))
            checkpoint = self._existing_trim_plan_checkpoint(job)
            if checkpoint is not None:
                saved = checkpoint["plan"]
                if saved.get("target_length") != self.config.target_length or (
                    self.config.target_length is not None
                    and saved.get("policy_version") != NATURAL_PAUSE_POLICY_VERSION
                ):
                    raise WorkerError(
                        "Saved trim policy differs from current target policy. "
                        "Restart this source's processing and review explicitly; "
                        "existing subtitles and approvals cannot be reused on a new timeline."
                    )
            if checkpoint is None:
                plan = self._trim_planner(
                    input_file=original_path,
                    target_length=self.config.target_length,
                    noise_threshold=self.config.noise_threshold,
                    min_duration=self.config.min_duration,
                    pad_sec=self.config.pad_sec,
                    temp_dir=job_dir,
                )
                checkpoint = self._trim_plan_checkpoint(job, plan)
                self._patch(f"/{job_id}/checkpoints", {"lease_token": lease_token, "trim_plan": checkpoint})
            self._write_checkpoint(job_dir / "trim-plan.json", checkpoint)
            segments = [(float(start), float(end)) for start, end in checkpoint["plan"]["segments_to_keep"]]
            approved_title = str(job.get("approved_title") or "").strip()
            if approved_title:
                self._render_and_upload_final_variants(
                    job, original_path, job_dir, lease_token, segments, approved_title,
                )
                self._post(f"/{job_id}/complete", {"lease_token": lease_token})
                return
            if not segments:
                self._post(f"/{job_id}/waiting", {"lease_token": lease_token, "reason": "trim-plan-ready; no retained speech"})
                return
            if not self._has_audio(original_path):
                self._post(f"/{job_id}/waiting", {"lease_token": lease_token, "reason": "trim-plan-ready; source has no audio"})
                return
            transcript = str(job.get("review_transcript") or "").strip()
            title = str(job.get("generated_title") or "").strip()
            srt_text = str(job.get("srt_text") or "")
            review_audio: Path | None = None
            if not transcript or not title:
                review_audio = job_dir / "review.ogg"
                self._review_audio_builder(original_path, review_audio, segments)
                transcript, title = self._analyze_review_audio(review_audio)
                self._patch(
                    f"/{job_id}/checkpoints",
                    {"lease_token": lease_token, "review_transcript": transcript, "generated_title": title},
                )
            srt_path = job_dir / "subtitles.srt"
            if not srt_text:
                self._subtitle_generator(input_file=original_path, segments=segments, output_path=srt_path, work_dir=job_dir / "subtitle-work", api_key=self._require_openrouter_key(), log_dir=job_dir)
                srt_text = srt_path.read_text(encoding="utf-8")
                if not srt_text.strip(): raise WorkerError("Subtitle generation returned empty SRT")
                self._patch(f"/{job_id}/checkpoints", {"lease_token": lease_token, "srt_text": srt_text})
            else:
                srt_path.write_text(srt_text, encoding="utf-8")
            if not bool(job.get("review_audio_uploaded")):
                if review_audio is None:
                    review_audio = job_dir / "review.ogg"
                    self._review_audio_builder(original_path, review_audio, segments)
                self._upload_artifact(job_id, lease_token, "review_audio", review_audio, title, "audio/ogg")
            if not bool(job.get("subtitle_uploaded")):
                self._upload_artifact(job_id, lease_token, "subtitle", srt_path, title, "application/x-subrip")
            self._post(
                f"/{job_id}/waiting",
                {"lease_token": lease_token, "reason": "waiting for title review"},
            )

    def _render_and_upload_final_variants(
        self, job: Mapping[str, Any], original_path: Path, job_dir: Path, lease_token: str,
        segments: list[tuple[float, float]], approved_title: str,
    ) -> None:
        """Render the two served variants from durable data after human approval."""
        if not segments:
            raise WorkerError("Cannot render final variants without retained speech")
        job_id = str(job["id"])
        srt_text = str(job.get("srt_text") or "")
        if not srt_text.strip():
            raise WorkerError("Cannot render final variants without a checkpointed SRT")
        srt_path = job_dir / "subtitles.srt"
        srt_path.write_text(srt_text, encoding="utf-8")
        trim_script = write_trim_script_from_plan(
            input_file=original_path, temp_dir=job_dir,
            target_length=self.config.target_length, noise_threshold=self.config.noise_threshold,
            min_duration=self.config.min_duration, pad_sec=self.config.pad_sec,
            segments_to_keep=segments,
        )
        title_path = job_dir / "approved-title.txt"
        title_path.write_text(approved_title, encoding="utf-8")
        logo_path = self._download_project_logo(job_id, lease_token, job_dir) if self.config.enable_logo_overlay else None
        if self.config.enable_title_overlay or self.config.enable_logo_overlay:
            prepare_video_overlays(
                input_file=original_path, temp_dir=job_dir, title_path=title_path,
                title_font=self.config.title_font, enable_title_overlay=self.config.enable_title_overlay,
                enable_logo_overlay=self.config.enable_logo_overlay,
                title_y_fraction=None, title_height_fraction=None,
                logo_path=logo_path,
            )
        no_overlay = job_dir / "no-overlay.mp4"
        if not bool(job.get("no_overlay_uploaded")):
            trim_single_video(
                input_file=original_path, output_dir=job_dir, output_basename="no-overlay",
                noise_threshold=self.config.noise_threshold, min_duration=self.config.min_duration,
                pad_sec=self.config.pad_sec, target_length=self.config.target_length,
                encoder=self.config.encoder, temp_dir=job_dir, metadata_title=approved_title,
                trim_script_path=trim_script,
            )
            mux_srt_track(no_overlay, srt_path)
            validate_target_duration(no_overlay, self.config.target_length)
            self._upload_artifact(job_id, lease_token, "no_overlay_video", no_overlay, approved_title, "video/mp4")
        final_video = job_dir / "final.mp4"
        if not bool(job.get("overlaid_uploaded")):
            trim_single_video(
                input_file=original_path, output_dir=job_dir, output_basename="final",
                noise_threshold=self.config.noise_threshold, min_duration=self.config.min_duration,
                pad_sec=self.config.pad_sec, target_length=self.config.target_length,
                encoder=self.config.encoder, title_path=title_path, title_font=self.config.title_font,
                enable_title_overlay=self.config.enable_title_overlay,
                enable_logo_overlay=self.config.enable_logo_overlay, temp_dir=job_dir,
                metadata_title=approved_title, trim_script_path=trim_script, logo_path=logo_path,
            )
            mux_srt_track(final_video, srt_path)
            validate_target_duration(final_video, self.config.target_length)
            self._upload_artifact(job_id, lease_token, "overlaid_video", final_video, approved_title, "video/mp4")

    def _require_openrouter_key(self) -> str:
        if not self.config.openrouter_api_key:
            raise WorkerError("OPENROUTER_API_KEY is required for missing model checkpoints")
        return self.config.openrouter_api_key

    def _analyze_review_audio(self, review_audio: Path) -> tuple[str, str]:
        """Use Media Manager's worker-authenticated canonical review-analysis path."""
        try:
            return analyze_review_ogg(
                self._client, self._url("/review-analysis"), self.config.worker_token, review_audio,
            )
        except ReviewAnalysisError as exc:
            raise WorkerError(str(exc)) from exc

    @staticmethod
    def _create_review_audio(input_path: Path, output_path: Path, segments: list[tuple[float, float]]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        graph = build_audio_concat_filter_graph(segments)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(input_path), "-filter_complex", graph, "-map", "[outa]", "-t", "180", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", str(output_path)], check=True, capture_output=True)

    @staticmethod
    def _has_audio(path: Path) -> bool:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
        return bool(result.stdout.strip())

    def _upload_artifact(self, job_id: str, lease_token: str, kind: str, path: Path, title: str, mime: str) -> None:
        digest = self._file_sha256(path); size = path.stat().st_size
        body = {"lease_token": lease_token, "kind": kind, "size": size, "checksum_sha256": digest, "title": title, "duration": self._duration(path) if mime.startswith("video/") else 0}
        initiated = self._post(f"/{job_id}/artifacts/initiate", body)
        if not initiated.get("already_uploaded"):
            with path.open("rb") as stream:
                response = self._client.put(str(initiated["upload_url"]), content=stream, headers={"Content-Type": mime})
                response.raise_for_status()
        self._post(f"/{job_id}/artifacts/complete", body)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _duration(path: Path) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            check=True, capture_output=True, text=True,
        )
        duration = float(result.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise WorkerError("Rendered video has an invalid duration")
        return duration

    def _url(self, path: str) -> str:
        return f"{self.config.service_url}/internal/source-processing/{quote(self.config.project, safe='')}{path}"

    def _headers(self) -> dict[str, str]:
        return {"X-Source-Processing-Token": self.config.worker_token}

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", path, body)

    def _patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("PATCH", path, body)

    def _request_json(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.request(method, self._url(path), headers=self._headers(), json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WorkerError(f"Source-processing {method} {path} failed: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise WorkerError(f"Source-processing {method} {path} returned an invalid response")
        return payload

    def _download_original(self, url: str, destination: Path) -> None:
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with self._client.stream("GET", url) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            temporary.replace(destination)
        except (OSError, httpx.HTTPError) as exc:
            temporary.unlink(missing_ok=True)
            raise WorkerError(f"Original download failed: {exc}") from exc

    def _download_project_logo(self, job_id: str, lease_token: str, job_dir: Path) -> Path | None:
        """Fetch the current project PNG only for the overlaid final."""
        destination = job_dir / "project-overlay-logo.png"
        try:
            with self._client.stream(
                "GET", self._url(f"/{job_id}/overlay-logo"),
                headers={**self._headers(), "X-Source-Processing-Lease-Token": lease_token},
            ) as response:
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except (OSError, httpx.HTTPError) as exc:
            destination.unlink(missing_ok=True)
            raise WorkerError(f"Project overlay logo download failed: {exc}") from exc
        if destination.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            destination.unlink(missing_ok=True)
            raise WorkerError("Project overlay logo is not a PNG file")
        return destination

    @staticmethod
    def _verify_checksum(path: Path, expected: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise WorkerError("Claim did not include a valid original checksum")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise WorkerError("Downloaded original checksum did not match the claimed source")

    def _heartbeat_once(self, job_id: str, lease_token: str) -> None:
        self._post(f"/{job_id}/heartbeat", {"lease_token": lease_token})

    @contextmanager
    def _heartbeat(self, job_id: str, lease_token: str) -> Iterator[None]:
        stop = threading.Event()
        failed: list[BaseException] = []

        def renew() -> None:
            while not stop.wait(self.config.heartbeat_interval_sec):
                try:
                    self._heartbeat_once(job_id, lease_token)
                except BaseException as exc:  # surface the fencing failure to the job owner
                    failed.append(exc)
                    stop.set()
                    return

        thread = threading.Thread(target=renew, name=f"source-processing-{job_id}", daemon=True)
        thread.start()
        try:
            yield
            if failed:
                raise WorkerError(f"Source-processing heartbeat failed: {failed[0]}")
        finally:
            stop.set()
            thread.join(timeout=max(1.0, self.config.heartbeat_interval_sec + 1.0))

    def _fail(self, job: Mapping[str, Any], message: str) -> None:
        try:
            job_id, lease_token, _ = self._job_fields(job)
            self._post(f"/{job_id}/fail", {"lease_token": lease_token, "error": message[:2000]})
        except Exception:
            pass

    @staticmethod
    def _job_fields(job: Mapping[str, Any]) -> tuple[str, str, str]:
        job_id = str(job.get("id", ""))
        lease_token = str(job.get("lease_token", ""))
        download_url = str(job.get("original_download_url", ""))
        if not job_id or not lease_token or not download_url.startswith(("http://", "https://")):
            raise WorkerError("Malformed source-processing job")
        return job_id, lease_token, download_url

    def _job_dir(self, job_id: str) -> Path:
        if not _SAFE_PATH_PART.fullmatch(job_id):
            raise WorkerError("Unsafe source-processing job ID")
        return self.config.work_dir / self.config.project / job_id

    @staticmethod
    def _safe_original_name(job: Mapping[str, Any]) -> str:
        raw = Path(str(job.get("original_filename") or "original.bin")).name
        return raw if _SAFE_PATH_PART.fullmatch(raw) else "original.bin"

    @staticmethod
    def _trim_plan_checkpoint(job: Mapping[str, Any], plan: TrimPlan) -> dict[str, Any]:
        data = asdict(plan)
        data["segments_to_keep"] = [[start, end] for start, end in plan.segments_to_keep]
        return {
            "version": 1,
            "source_id": str(job.get("source_id", "")),
            "original_checksum_sha256": str(job.get("original_checksum_sha256", "")),
            "plan": data,
        }

    @staticmethod
    def _existing_trim_plan_checkpoint(job: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return a previously server-fenced plan only when its identity and shape match."""
        checkpoint = job.get("trim_plan")
        if not isinstance(checkpoint, dict):
            return None
        if checkpoint.get("version") != 1:
            return None
        if checkpoint.get("source_id") != job.get("source_id"):
            return None
        if checkpoint.get("original_checksum_sha256") != job.get("original_checksum_sha256"):
            return None
        plan = checkpoint.get("plan")
        if not isinstance(plan, dict):
            return None
        segments = plan.get("segments_to_keep")
        if not isinstance(segments, list):
            return None
        previous_end = -1.0
        for segment in segments:
            if not isinstance(segment, list) or len(segment) != 2:
                return None
            start, end = segment
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                return None
            if not math.isfinite(start) or not math.isfinite(end):
                return None
            if start < 0 or end <= start or start < previous_end:
                return None
            previous_end = float(end)
        try:
            encoded = json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return None
        if len(encoded) > 64 * 1024:
            return None
        return checkpoint

    @staticmethod
    def _write_checkpoint(path: Path, checkpoint: Mapping[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(checkpoint, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)


def main() -> int:
    """Run the durable worker continuously; idle polling does not restart Docker."""
    with SourceProcessingWorker(WorkerConfig.from_env()) as worker:
        while True:
            try:
                if not worker.run_once():
                    time.sleep(5)
            except WorkerError as exc:
                # The error has already been persisted through the lease-fenced
                # failure endpoint. Keep the worker available for the next job.
                print(f"SOURCE_PROCESSING_WORKER_ERROR {exc}", flush=True)
                time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
