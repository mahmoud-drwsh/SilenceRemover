# SilenceRemover flow (after rename-first / data.json refactor)

## High-level

```mermaid
flowchart TB
  subgraph input [Input]
    raw[raw/ video files]
  end

  subgraph phase1 [Phase 1 per video]
    raw --> full_audio[create_silence_removed_audio]
    full_audio --> no_silence["temp/{basename}_no_silence.wav"]
    no_silence --> first5[extract_first_5min_from_audio]
    first5 --> snippet["temp/{basename}_snippet.wav"]
    snippet --> transcribe[transcribe_single_video]
    transcribe --> api1[OpenRouter: transcript]
    api1 --> api2[OpenRouter: title]
    api2 --> data1[update output/data.json]
  end

  subgraph phase2 [Phase 2 per video]
    data1 --> read_title[read title from data.json]
    read_title --> trim[trim_single_video with output_basename]
    trim --> out_mp4["output/Title.mp4"]
    out_mp4 --> data2[set completed true in data.json]
  end

  subgraph outputs [Outputs]
    data_json[output/data.json]
    out_videos[output/*.mp4]
    temp_files[temp/*.wav, *.txt]
  end
```

## Step-by-step

| Step | What | Where |
|------|------|--------|
| 1 | Full silence-removed **audio only** (same algorithm as video trim, `-vn`) | `temp/{basename}_no_silence.wav` |
| 2 | First 5 min of that audio | `temp/{basename}_snippet.wav` |
| 3 | Transcribe snippet (two prompts: transcript, then title) | temp `.txt` / `.title.txt` + **data.json** |
| 4 | Full **video+audio** trim with title as filename | `output/{Title}.mp4` |
| 5 | Mark `completed: true` | **output/data.json** |

## data.json shape

- **Path:** `output/data.json`
- **Shape:** `{ "original_video.mp4": { "transcript": "...", "title": "...", "completed": true } }`
- Resume: Phase 1 skipped if `transcript` and `title` present; Phase 2 skipped if `completed` is true.

## Directory layout

- **input_dir** (e.g. `raw/`) – source videos
- **output/** – `data.json` + final trimmed videos (`Title.mp4`)
- **temp/** – `_no_silence.wav`, `_snippet.wav`, `.txt`, `.title.txt` (no “renamed” folder)
