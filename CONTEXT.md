# Media Processing Glossary

## Core media

- **Source recording**: The raw input video selected for processing.
- **Original**: The immutable uploaded copy of a source recording. One original is identified by its source ID.
- **Derived media**: Any non-original file produced from, or attached to, an original: the no-overlay video, review audio, or a designer video. Every derived-media record links directly to its original through the source ID.
- **Derived video**: Any processed video created from an original. A derived video links back to exactly one original.
- **Source ID**: The stable identifier shared by a source recording and its original. Derived videos retain this as their original link.
- **Derived ID**: The distinct identifier for one derived video. The no-overlay video uses `<source_id>-no-overlay`.

## Video variants

- **No-overlay video**: The single silence-removed derived video for an original. It has no title banner, no logo, and no subtitles. Its metadata title and its download name are the approved title. Its media variant is `no-overlay`. Old no-overlay videos (made before spec #44) can still contain an embedded Arabic subtitle track. The system does not change these files.
- **Designer video**: The active designer revision: a designer-uploaded presentation linked to one no-overlay video. It shares the original of that no-overlay video through the source ID. It does not change pipeline output.
- **Designer revision**: An immutable designer-uploaded video linked to a no-overlay video. A no-overlay video can have many revisions. Exactly one revision is its active designer video. The active pointer is on the no-overlay row.
- **Canonical video card**: The single list entry for an original's no-overlay video. The designer video and the original are linked actions on the same card. They are never independent list entries.
- **Review audio**: The audio file used to review and approve a generated title. It is derived media linked directly to the original, not to a video.
- **Silence-removed video**: A derived video produced by removing detected silence according to the pipeline's trim policy. The no-overlay video is the only silence-removed video that the pipeline makes.
- **Legacy designer link**: A designer revision that points at an old overlaid video ID (`<source_id>`) or uses the old `-designer` ID suffix. A temporary fallback shows these revisions on the correct card. The data move (see `docs/no-overlay-data-move-runbook.md`) moves these links to the no-overlay ID. After the data move, the fallback can be removed.
- **Retired output**: The overlaid video, the title banner, the project logo, the subtitle SRT, the selectable subtitle track, and the remux job are removed. Only legacy rows and the data move use these terms.

## Pipeline state

- **Generated title**: The title extracted from the transcription and used to label derived media.
- **Completed marker**: Local evidence that the no-overlay encode finished for a source recording. It stays valid if the local MP4 is later moved.
- **Uploaded**: Metadata and media bytes have been accepted by Media Manager.
- **Linked**: A derived record references its original through the source ID.
- **Backfill**: The one-time repair of a missing derived-to-original link when both records already exist.
- **Self-heal**: Repairing a missing derived-to-original link when the matching original arrives during a later pipeline retry.

## Media Manager lifecycle

- **Pending**: A delivered derived video awaiting the normal publishing step.
- **Published**: A video promoted for its delivery channels after its audio review is ready.
- **Project**: The Media Manager collection containing originals and all derived media for one processing destination.

## Organization

- **Virtual view**: A system-provided filtered view of media, not a user-created container. The video views are All, Needs Designer, Designer Video, Pending, and Trash. A bookmark with a removed view name (Pipeline Final or No Overlay) opens All. Audio Review has Todo and Approved.
- **Folder**: A user-facing publishing destination. Folders are not part of the target organization model.
- **User tag**: A user-assigned label used to organize or publish media. User tags are not part of the target organization model.
