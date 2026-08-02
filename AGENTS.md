# Session change summaries for AI agents

Use [`CONTEXT.md`](CONTEXT.md) as the canonical glossary for media-processing terms such as original, derived video, overlaid video, no-overlay video, linked, backfill, and self-heal.

After code or config changes, agents append short notes here. When this file grows past ~20 lines, **replace** the changelog with an updated condensed section instead of keeping one bullet per file forever.

## Agent Workflow Rules

- **ALWAYS use the `question` tool** when clarification is needed, when weighing tradeoffs, or when the user might have a preference. Do not ask questions inline in text responses—use the dedicated tool.
- **NEVER** hardcode the domain name in the code.

## Condensed changelog

- **Architecture**: Core orchestration is `src/app/pipeline.py`; media, FFmpeg, startup, and LLM concerns are split under `src/` and `packages/`. `README.md` and `ALGO.md` document the processing flow.
- **Media processing**: The pipeline generates trim scripts, snippets, transcripts, titles, optional title/logo overlays, and silence-removed HEVC MP4s. It handles audio-less inputs, locked recordings, and QSV-or-x265 encoding resolution.
- **Media Manager**: `remote-js/` is the Bun/Hono service with Postgres metadata and S3-compatible bytes. Pipeline uploads use authenticated presigned sessions; originals, audio, and videos are linked by stable source IDs.
- **Original links and downloads**: Startup backfills legacy links; an original retry self-heals matching derived rows. Linked derived cards provide inline original downloads without an Originals view.
- **Video variants**: Each source can have an overlaid video and a silence-removed no-overlay companion. No-overlay companions use the `no-overlay` tag/folder and share their original’s source ID.
- **No-overlay completion**: Companion MP4s are stored under `temp/no_overlay/`; `temp/no_overlay_completed/{source-id}.txt` is independent from the standard completion marker. It prevents regeneration after the companion MP4 has been moved and can adopt existing local/server companions. The copy shortcut applies only to MP4 inputs, and a present mislabeled legacy companion self-heals through re-encoding; missing local companions retain their marker. Multipart completion reports server validation detail to the pipeline.
- **Workflow state**: Audio is reviewed through tags; normal overlaid video publishing continues to use the existing pending-to-channel flow. No-overlay companions remain in their dedicated folder.
- **Validation**: Python tests cover pipeline behavior; `remote-js` has Bun tests and an isolated Docker Compose integration environment using Postgres and MinIO.
