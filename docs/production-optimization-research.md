# Production pipeline optimization research

Research date: 2026-08-02. This is a code and primary-documentation review,
not a production trace. Instrumentation must precede concurrency or quality
changes.

## Current critical path

The pipeline processes each phase across the whole batch. It runs a full
overlaid encode in Phase 8 and a separate no-overlay encode in Phase 9; both
call `trim_single_video` with the same input and trim plan. See
[pipeline.py](../src/app/pipeline.py), [trim.py](../src/media/trim.py), and
[transcode.py](../src/ffmpeg/transcode.py). For 829 sources that is at least
1,658 output encodes, as well as duplicate input decode/filtering.

After a direct presigned upload, Media Manager downloads the full object into
its temp directory, computes SHA-256, sniffs MIME, and calls `ffprobe` before
committing metadata. See [uploads.ts](../remote-js/src/routes/uploads.ts) and
[storage.ts](../remote-js/src/storage.ts). So completion latency includes a
second full object read plus service disk I/O.

## Ranked opportunities

### 1. Measure and reduce duplicate video processing — highest expected impact

The paired output requirement currently schedules two FFmpeg processes for the
same silence-removed timeline. Prototype a single FFmpeg process that decodes
and trims once, splits labelled video/audio pads, and emits clean and
overlay-bearing outputs. FFmpeg explicitly supports complex filter graphs and
labelled output pads ([official filtergraph documentation](https://ffmpeg.org/ffmpeg.html#Complex-filtergraphs)). Benchmark representative short, median,
and long recordings against the current two-process implementation; retain the
existing approach unless output duration, AV sync, visual parity, and quality
all remain correct and wall time is materially lower.

The existing QSV/AMF/x265 selection is in
[encoding_resolver.py](../src/ffmpeg/encoding_resolver.py). Do not assume QSV
eliminates this cost: FFmpeg states QSV zero-copy accelerated transcoding needs
a compatible decoder/encoder and **no filters**; hardware decode can also lose
time to memory copies ([official hardware-acceleration documentation](https://ffmpeg.org/ffmpeg.html#Advanced-Video-options)). Our trim/overlay graph means
actual graph benchmarks are required.

### 2. Remove full post-upload relay from the synchronous completion path

Keep validation, but split it into synchronous object existence/size checks and
asynchronous SHA-256, MIME, and duration verification. Persist a
`pending_verification` state and keep it hidden from downloads until the worker
passes. This retains the safety invariant while removing an object-sized read,
temporary disk write, and `ffprobe` from the user-visible completion request.
It directly addresses the observed path where byte upload reached 100% before
completion failed.

### 3. Simplify measured 70–80 MiB uploads before adding parallelism

Cloudflare R2 recommends a single PUT for small/medium files under about
100 MiB; multipart is for large files or parallelism/resumability
([R2 upload guidance](https://developers.cloudflare.com/r2/objects/upload-objects/)).
The observed no-overlay uploads (roughly 70–80 MiB) fit that range, whereas the
current service uses 8 MiB multipart parts for video. A measured threshold
experiment could eliminate roughly 8–10 part PUTs and multipart completion
complexity per file. First compare full transfer + completion p50/p95; do not
change it merely for fewer requests.

If multipart remains warranted, R2 supports parallel part upload, and its S3
example uses parallelism (default 4). It requires all non-final parts to have
equal size and requires the exact returned ETags at completion
([R2 multipart details](https://developers.cloudflare.com/r2/objects/upload-objects/#multipart-upload-details)). The current Python client uploads parts serially. Trial a bounded 2–4 workers only after observing bandwidth, server load, and error rate. Keep writes for one object key serialized: R2 documents a one-write-per-second-per-key limit, with `429` on violation
([R2 error codes](https://developers.cloudflare.com/r2/api/error-codes/)).

### 4. Add durable phase metrics first — low risk, prerequisite

Record redacted structured events for source ID, phase duration, output bytes,
encoder, FFmpeg `speed`, upload bytes/sec, part count, and completion-verifier
duration. Aggregate p50/p95 after one production-equivalent batch. This tells
us whether duplicate encode, transfer, or verification is actually dominant
and separates client transfer time from server completion time.

### 5. Do not prioritize OpenRouter caching for first-pass throughput

Source-specific transcription bodies should almost never be identical.
OpenRouter response caching only hits when API key, model, endpoint, streaming
mode, and complete request body match; concurrent identical calls are not
coalesced ([OpenRouter response caching](https://openrouter.ai/docs/guides/features/response-caching)). It is useful for idempotent retry recovery—hits are
zero-billed and avoid provider rate limits—but not as a batch-wide transcription
speedup. If used, apply only to safe exact retries and account for the
documented account-level ZDR limitation.

## Proposed sequence

1. Add phase p50/p95 timing and throughput telemetry.
2. Benchmark paired-output FFmpeg processing and QSV/x265 on representative
   filtered inputs; adopt only with correctness parity.
3. Decouple completion verification while retaining hidden-until-verified
   delivery.
4. Use the resulting upload measurements to decide between single PUT and
   bounded multipart parallelism.
