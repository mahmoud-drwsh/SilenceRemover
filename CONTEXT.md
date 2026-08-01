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
- **Companion video**: A derived video that represents the same source and silence-removal result as another derived video, but differs in presentation.
- **Silence-removed video**: A derived video produced by removing detected silence according to the pipeline's trim policy. Both video variants are silence-removed.

## Pipeline state

- **Generated title**: The title extracted from the transcription and used to label derived media.
- **Completed marker**: Local evidence that the standard overlaid final encode finished for a source recording.
- **No-overlay completed marker**: Separate local evidence that the no-overlay companion was created or adopted. It remains valid if the local companion MP4 is later moved.
- **Uploaded**: Metadata and media bytes have been accepted by Media Manager.
- **Linked**: A derived record references its original through the source ID.
- **Backfill**: The one-time repair of a missing derived-to-original link when both records already exist.
- **Self-heal**: Repairing a missing derived-to-original link when the matching original arrives during a later pipeline retry.

## Media Manager lifecycle

- **Pending**: A delivered derived video awaiting the normal publishing step.
- **Published**: A video promoted for its delivery channels after its audio review is ready.
- **Project**: The Media Manager collection containing originals and all derived media for one processing destination.
