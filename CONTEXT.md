# Media Processing Glossary

## Core media

- **Source recording**: The raw input video selected for processing.
- **Original**: The immutable uploaded copy of a source recording. One original is identified by its source ID.
- **Derived video**: Any processed video created from an original. A derived video links back to exactly one original.
- **Source ID**: The stable identifier shared by a source recording and its original. Derived videos retain this as their original link.
- **Derived ID**: The distinct identifier for one derived video variant. It must not overwrite another variant from the same source.

## Video variants

- **Overlaid video**: The standard silence-removed derived video. It may include the generated title banner and optional logo.
- **No-overlay video**: A second silence-removed derived video with neither title banner nor logo. It is a companion to—not a replacement for—the overlaid video.
- **Designer video**: A designer-uploaded replacement presentation linked to one selected pipeline-final video. It shares that final video's original through the source ID, but does not change pipeline output.
- **Companion video**: A derived video that represents the same source and silence-removal result as another derived video, but differs in presentation.
- **Silence-removed video**: A derived video produced by removing detected silence according to the pipeline's trim policy. Both video variants are silence-removed.
- **Subtitle SRT**: A pipeline-generated SubRip text file. Gemini transcribes bounded groups of retained speech as plain text; the pipeline deterministically derives cue timings from the retained timeline.
- **Selectable subtitle track**: The Arabic `mov_text` track muxed into both silence-removed video variants. It is disabled by default and is never burned into pixels.

## Pipeline state

- **Generated title**: The title extracted from the transcription and used to label derived media.
- **Completed marker**: Local evidence that the standard overlaid final encode finished for a source recording.
- **No-overlay completed marker**: Separate local evidence that the no-overlay companion was created or adopted. It remains valid if the local companion MP4 is later moved.
- **Subtitle mux marker**: Local evidence that the current SRT has been muxed into both final variants.
- **Uploaded**: Metadata and media bytes have been accepted by Media Manager.
- **Linked**: A derived record references its original through the source ID.
- **Backfill**: The one-time repair of a missing derived-to-original link when both records already exist.
- **Subtitle backfill**: A one-time operation that transcribes an existing silence-removed video on its served timeline, uploads its deterministic SRT, and remuxes that track into the linked video variants.
- **Remux job**: A durable, checksum-pinned request to add a verified SRT as a selectable track by stream-copying existing video and audio; it does not re-encode them.
- **Self-heal**: Repairing a missing derived-to-original link when the matching original arrives during a later pipeline retry.

## Media Manager lifecycle

- **Pending**: A delivered derived video awaiting the normal publishing step.
- **Published**: A video promoted for its delivery channels after its audio review is ready.
- **Project**: The Media Manager collection containing originals and all derived media for one processing destination.
