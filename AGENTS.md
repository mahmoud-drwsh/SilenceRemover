# Session change summaries for AI agents

Use [`CONTEXT.md`](CONTEXT.md) as the canonical glossary for media-processing terms such as original, derived video, overlaid video, no-overlay video, linked, backfill, and self-heal.

After code or config changes, agents append short notes here. When this file grows past ~20 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Agent Workflow Rules

- **ALWAYS use the `question` tool** when clarification is needed, when weighing tradeoffs, or when the user might have a preference. Do not ask questions inline in text responses—use the dedicated tool.
- **NEVER** hardcode the domain name in the code.

## Condensed changelog

- **Architecture**: Core orchestration is `src/app/pipeline.py`; media, FFmpeg, startup, and LLM concerns are split under `src/` and `packages/`. `README.md` and `ALGO.md` document the processing flow.
- **Media processing**: The pipeline generates trim scripts, snippets, transcripts, titles, optional title/logo overlays, and silence-removed HEVC MP4s. It handles audio-less inputs, locked recordings, and VAAPI-, QSV-, or x265-based encoding resolution.
- **Media Manager**: `remote-js/` is the Bun/Hono service with Postgres metadata and S3-compatible bytes. Pipeline uploads use authenticated presigned sessions; originals, audio, and videos are linked by stable source IDs.
- **Original links and downloads**: Startup backfills legacy links; an original retry self-heals matching derived rows. Linked derived cards provide inline original downloads without an Originals view.
- **Video variants**: Each source can have an overlaid video and a silence-removed no-overlay companion. No-overlay companions use the `no-overlay` tag/folder and share their original’s source ID. Designer videos are Media Manager-only uploads linked to a selected pipeline-final through `designer_of_id`; the service derives their source link and keeps one active designer video per final. Startup surgically backfills only empty-tag legacy companions whose `-no-overlay` ID exactly matches a linked original source ID.
- **No-overlay completion**: Companion MP4s are stored under `temp/no_overlay/`; `temp/no_overlay_completed/{source-id}.txt` is independent from the standard completion marker. It prevents regeneration after the companion MP4 has been moved and can adopt existing local/server companions. The copy shortcut applies only to MP4 inputs, and a present mislabeled legacy companion self-heals through re-encoding; missing local companions retain their marker. Multipart completion reports server validation detail to the pipeline.
- **No-overlay reconciliation**: Startup resolves an existing companion through the pipeline-final row’s `no_overlay_id`, so completed uploads remain phase-level skips and do not emit per-file check/processing output.
- **Workflow state**: Audio is reviewed through tags; normal overlaid video publishing continues to use the existing pending-to-channel flow. No-overlay companions remain in their dedicated folder.
- **Validation**: Python tests cover pipeline behavior; `remote-js` has Bun tests and an isolated Docker Compose integration environment using Postgres and MinIO.
- **Designer UI regression**: Video-card menu state is defined for every filter before the shared footer is rendered, preventing a card-rendering `ReferenceError`.
- **Audio review**: The audio UI is a title-review queue only: playback, title editing, and explicit approve/reopen actions; it does not expose media-management controls.
- **Review ordering**: Non-admin title review is always oldest first and has no sorting control; admin sorting remains available.
- **Trash access**: Video trash controls are admin-only; non-admin title reviewers can discard unusable audio from the review queue.
- **Designer queue**: The `needs-designer` video filter returns only pipeline finals without a non-trashed linked designer video; non-admin designers see this focused queue.
- **Focused folders**: Single-purpose non-admin queues hide the redundant folder navigation.
- **Bulk audio approval**: Admin-mode audio review offers a confirmed bulk action that marks only non-trashed `todo` audio as `ready` and returns the affected count.
- **Subtitle delivery**: Linked video cards expose the embedded subtitle track through MP4 downloads and provide a separate SRT download for `{source-id}-subtitles`. The deterministic normalizer bounds cues and repairs legacy flattened cue headers and non-padded millisecond timestamps before checksum-pinned remuxing. Pipeline startup treats an existing server SRT as completed, preventing backfilled sources from spending OpenRouter credits again.
- **Subtitles**: Subtitle generation is independent of the title snippet: OpenRouter's dedicated Qwen3 ASR endpoint returns plain Arabic text for bounded, silence-aligned retained-speech groups; local code owns deterministic SRT timing, and both final variants receive a separate selectable Arabic track. SRT uploads use the deterministic `{source-id}-subtitles` Media Manager ID.
- **Subtitle backfill**: Historical SRTs are generated against an existing silence-removed variant's served timeline and strictly normalized/validated. Durable checksum-pinned remux jobs lease work to a resumable local worker, stage one temporary object, reject changed inputs, atomically promote verified output, and preserve video metadata and links.
- **Subtitle compatibility**: A deterministic no-LLM normalization tool splits oversized cues into editor-friendly 6–10 second ranges while preserving all Arabic text and parent timing; MP4 downloads keep embedded `mov_text`, with sidecar SRT retained as an optional download.
