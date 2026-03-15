# Session change summaries for AI agents

Entries below are appended by the agent after making code or config changes.

- `main.py`: Removed DEBUG global, --debug CLI flag, and debug parameters from run_phase1_for_video and run_phase2_for_video.
- `src/trim.py`: Removed DEBUG global, debug parameter from create_silence_removed_audio and trim_single_video, and all debug print branches in _build_segments_to_keep.
- `src/silence_utils.py`: Removed debug parameter and all debug print blocks from detect_silence_points.
- `src/config.py`: Set OPENROUTER_DEFAULT_MODEL and OPENROUTER_TITLE_MODEL defaults to google/gemini-2.5-flash-lite.
- `src/config.py`: Set OPENROUTER_TITLE_MODEL default to google/gemini-3.1-flash-lite-preview for title generation.
