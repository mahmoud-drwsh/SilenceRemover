# Natural pauses under a three-minute video limit

Research and implementation review for Mahmoud • 5 September 2026

## Decision

Replace target-driven loudness-threshold search with a **budget over fixed detected pauses**. Keep existing short gaps; cap excessively long detected pauses; remove only the additional pause time needed. Never turn up the detector threshold or cut off speech to force a duration. If the protected timeline cannot fit, fail explicitly and request a split or manual edit.

The prepared patch implements that bounded allocation and integration checks. The change is prepared for review as a draft PR. It is a candidate for Arabic listening validation, not a claim of perceptually proven naturalness. It does not deploy or merge the change.

## What is the shortest natural gap?

There is no supported universal number for every word boundary. Existing brief transitions are different from phrase, sentence, and rhetorical pauses. Do not insert a fixed gap between every word, and do not shorten every long pause to an ASR/VAD segmentation setting.

Liu and colleagues manipulated punctuation pauses in short English excerpts. Their listening experiments favored roughly 600 ms within sentences and 600–1,200 ms between sentences; very short 75/150 ms conditions were poorly rated. This is direct naturalness evidence, but it concerns English punctuation boundaries, not every word or Arabic lecture editing. The authors explicitly call for other-language research. [Liu et al., *Frontiers in Psychology*, 11 February 2022](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2022.778018/full).

A production study covering 24 readers, four hours, and six European languages found that faster speech avoids the longest pauses. Its manually annotated Dutch data distinguished short, often within-phrase pauses from longer boundary pauses. This supports preferentially shortening long pauses, but it did not test a listener-approved minimum. The authors also report that breaths can split a detected pause and that boundaries can be inaccurate. [Demol, Verhelst & Verhoeve, *A Study of Speech Pauses for Multilingual Time-Scaling Applications*, 2006](https://academic.sun.ac.za/su_clast/multiling/pdfs/demol.pdf).

A Japanese experiment tested 0–400 ms phrase pauses with speech-rate changes in noise. Nonzero pauses helped intelligibility, with useful effects around 300–400 ms in some conditions. **Intelligibility is not naturalness**, and those results do not certify a 100 or 300 ms Arabic editing floor. [Tanaka, Sakamoto & Suzuki, *Acoustical Science and Technology*, 2011](https://www.jstage.jst.go.jp/article/ast/32/6/32_6_264/_pdf/-char/en).

**Engineering recommendation:** begin with a conservative 600 ms floor for pauses that are shortened, preserve every existing gap below that duration, and allow up to 1.2 seconds for longer pauses. A 300 ms floor can be an experimental comparison, not the default or a scientific guarantee. No Arabic edited-video listening experiment found in this research establishes the requested universal minimum.

## Current implementation assessment

Inspected baseline: `packages/sr_trim_plan/api.py`, `src/media/silence_detector.py`, `src/ffmpeg/trim_script_bundle.py`, final rendering, and local/server orchestration.

| Baseline behavior | Problem for this task | Change |
|---|---|---|
| Binary-search threshold from −60 to −35 dB | The duration objective changes which audio is called silence; quiet speech may become eligible | Fixed −50 dB detector, independent of target |
| Detect 100 ms pauses; begin at 60 ms padding | Short natural transitions can be edited | Detect pauses at least 600 ms; preserve all shorter gaps |
| Resume at `silence_end - pad` | Despite two-sided wording in places, an edited internal gap retains only one `pad` | Keep half the allocated gap next to each speech boundary |
| Maximize one global padding value | No explicit retained-gap floor/ceiling | Explicit bounds and per-pause allocation |
| Return over-target best effort; swallow probe errors | Failure can look like a valid target-mode result | Actionable infeasibility and propagated detector errors |
| Skip analysis when source already fits | Long pauses escape the requested cap | Apply cap even to shorter sources |
| Estimate from float segment durations | Encoded duration may differ | Headroom plus strict probe before final acceptance/upload |

FFmpeg defines silence through a volume threshold and minimum duration, not linguistic interpretation. A fixed detector avoids duration-induced escalation but cannot prove all quiet speech safe. Its concat filter uses the longest stream per segment, so a sum of ideal cut durations is not a final-file guarantee. [FFmpeg official filter documentation, accessed 5 September 2026](https://ffmpeg.org/ffmpeg-filters.html#silencedetect), [concat](https://ffmpeg.org/ffmpeg-filters.html#concat).

## Proposed allocation

Let `D` be input length, `T` the exclusive target, and `B = T − 0.5 s` the planning budget. For under three minutes, use `--target-length 180`, giving a 179.5-second planning budget.

For each detected internal gap of length `g`, set a lower bound `l = min(g, 0.6)` and preferred upper bound `u = min(g, 1.2)`. Leading/trailing silence retains up to 0.2 seconds adjacent to speech. The edge buffer and rendering margin are engineering choices.

Let `P` be the duration outside detected gaps. The shortest permitted timeline is `M = P + sum(l)`. If `M > B`, reject the request. Otherwise compute total flexible pause time `F = sum(u − l)` and the available allowance `A = min(F, B − M)`. Allocate `r = l + (u − l) × A/F` to each pause (with the zero-slack case handled separately).

This keeps pause variation where the bounds permit it. It does not shorten below the floor. It may finish earlier than the budget because of the independent long-pause cap. Implementation uses integer microseconds and deterministic remainder allocation; cuts stay within the validated quiet intervals. Speech rate is unchanged, original sound is retained near both sides of each internal cut, and audio/video share one timeline.

**Calculated example:** a 185-second recording with five two-second detected gaps contains 175 seconds outside them. The 179.5-second budget permits 4.5 seconds across those gaps: retain 0.9 seconds each, removing 5.5 seconds in total. If protected content and minimum pauses instead total 185.6 seconds, the target is infeasible; lowering the pause floor automatically would violate the chosen policy.

## Alternatives and remaining limitations

- **VAD protection:** a good future enhancement is to forbid cuts wherever a conservatively configured speech detector reports speech, and cut only inside the remaining quiet regions. Silero's default minimum speech chunk is 250 ms and default side padding is 30 ms; those segmentation settings are not natural-pause limits and can discard short speech chunks. Dataset-specific validation is required before using VAD as edit authority. [Silero official utility source, accessed 5 September 2026](https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py).
- **ASR/phrase-aware allocation:** verified sentence/topic boundaries could justify longer protected pauses. The current title snippet does not provide reliable whole-recording boundaries. No semantic boundary labels are invented in this PR.
- **Speed changes or content edits:** these could make infeasible clips shorter, but they change the task. This implementation does neither.
- **Detection and cuts:** −50 dB is an initial conservative setting, not automatic noise-floor calibration. Very quiet speech, background noise, breaths, reverberation, and visual jump cuts still need review. No claim is made that every breath is retained or that every join is inaudible. The 1.2-second cap applies to each detected quiet interval, not a breath-fragmented linguistic pause.
- **Rendering:** fixed headroom is not a mathematical bound for every frame rate and cut count. The final duration gate rejects an overrun; automatic frame-aware replanning is not implemented. It never uses an unconditional final `-t` to cut speech.

## Use and rollout

The shared target-mode planner now uses this policy. Local use: `python main.py INPUT --target-length 180`. Non-target processing keeps its existing policy. Server worker use: configure `SOURCE_PROCESSING_TARGET_LENGTH=180`; unset preserves its previous non-target default. No running service was changed.

Target script cache keys include the policy and version. Existing server checkpoints with a different target/policy fail explicitly: reusing their approval/subtitles with a different timeline would be unsafe. Existing completed local outputs, subtitle markers, and already-uploaded files are not automatically regenerated. Evaluate with a fresh work/output directory; restart processing/review through the normal workflow for any source you intentionally migrate. Avoid a mixed old/new worker rollout against the same active jobs.

## Validation and acceptance

**Result: 538 Python tests passed**, with two pre-existing pytest warnings about helper tests returning values. Command: `PYTHONPATH=.:packages python -m pytest tests -q --tb=short`. Media fixtures were generated locally; the silence fixture was synthesized separately because the existing generator produced an empty output. A missing SOCKS dependency in the temporary test environment was resolved before the successful final run. No production endpoints or paid transcription requests were used.

Automated validation covers exact duration budgeting, protected-gap bounds, ordered cuts contained in quiet intervals, short-gap preservation, symmetric retained padding, edge handling, malformed inputs, unreachable targets, detector failure, cache versioning, worker configuration, and strict rejection at 180 seconds. Randomized tests exercise 300 multi-pause timelines. A real FFmpeg test processes a synthetic 186-second source with two five-second gaps and quiet −42 dB tone material, producing approximately 178.4 seconds. Synthetic tones test mechanics, not speech naturalness.

Before merging for regular use, compare original/old/new edits on representative Arabic clips with native listeners. Include quiet consonants, breaths, room noise, sentence/topic breaks, many cuts, continuous speech, and unreachable targets. Blind/randomize the order and rate naturalness, clipped words, breath discontinuity, and visual jumps separately; verify final duration independently. Retain original recordings. If the 600 ms policy fails the duration requirement, split/edit the source instead of silently relaxing it. No native-listener evaluation was performed in this session.

## Research scope and confidence

This review combined primary pause-production/perception research, official detector/rendering documentation, and the repository's implementation. Searches covered naturalness versus intelligibility, multilingual and Arabic applicability, silence compression, VAD behavior, and A/V concat timing. Findings converge on preserving short pauses and separating detection from allocation. Further broad searching is unlikely to certify a universal Arabic minimum; the remaining consequential gap requires listening to this project's recordings.

Confidence is high in the implementation mismatch and feasibility arithmetic, moderate in the conservative design direction, and limited for Arabic perceptual naturalness. The defaults are hypotheses for evaluation, not measurements from your speakers.
