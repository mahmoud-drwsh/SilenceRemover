# OpenRouter options for Arabic segment transcription

*Research snapshot: 2026-08-10. Sources are OpenRouter documentation/model
pages and first-party provider documentation only.*

## Cheaper-than-Qwen update (2026-08-10)

The live OpenRouter transcription catalog prices
`qwen/qwen3-asr-flash-2026-02-10` at **$0.000035/second**, or
**$0.0021/minute**. There is no cheaper catalog model that both explicitly
claims Arabic support and has shown acceptable quality in our production-audio
pilot.

| Candidate | Catalog rate | Relative to Qwen | Arabic and operational fit |
| --- | ---: | ---: | --- |
| `openai/whisper-large-v3-turbo` | $0.04/hour = **$0.000667/min** | 68% cheaper | OpenRouter says it covers 99+ languages, and Arabic is in the Whisper language set. It uses the dedicated STT endpoint and advertises very high speed. However, our segmented production pilot produced a repeatable hallucinated phrase, so price alone does not justify unattended use. |
| `openai/whisper-large-v3` | **$0.0015/min** | 29% cheaper | OpenRouter describes it as multilingual, noise-robust, and supporting word/segment timestamps. This is the only cheaper reasonable quality challenger, but the earlier corpus test omitted material speech on a whole-file request. Re-test on the same silence-aligned segments before considering it. |
| `nvidia/parakeet-tdt-0.6b-v3` | **$0.0015/min** | 29% cheaper | OpenRouter limits its language claim to official EU languages; Arabic is not one. It returns punctuation and segment timestamps, but is not a supported candidate for this Arabic corpus. |
| `fish-audio/transcribe-1` | $0.0001/second = **$0.006/min** | 186% more expensive | Automatic language detection and optional word alignment are advertised, but neither OpenRouter nor the provider evidence reviewed here explicitly guarantees Arabic. It is not cheaper. |
| `mistralai/voxtral-mini-transcribe` | **$0.003/min** | 43% more expensive | Dedicated STT, but the OpenRouter entry makes no Arabic-specific claim. It is not cheaper and performed below Qwen in the production pilot. |

Rates above come from OpenRouter's live transcription-filtered Models API and
model pages. The catalog uses model-specific units: Qwen and Fish are displayed
per second, Whisper/Parakeet/Voxtral per minute or hour. Always log the returned
`usage.seconds` and `usage.cost` rather than inferring the bill from the generic
`pricing.prompt` field. [OpenRouter transcription catalog](https://openrouter.ai/models?output_modalities=transcription),
[Qwen listing](https://openrouter.ai/qwen/qwen3-asr-flash-2026-02-10),
[Whisper Turbo pricing](https://openrouter.ai/openai/whisper-large-v3-turbo/pricing),
[Fish Transcribe 1](https://openrouter.ai/fish-audio/transcribe-1),
[Parakeet listing](https://openrouter.ai/nvidia/parakeet-tdt-0.6b-v3/uptime)

OpenRouter's dedicated endpoint accepts an optional ISO-639-1 language hint,
so requests should specify `language: "ar"`. Its generic response is plain text
plus exact usage. `verbose_json` and word/segment timestamps work only on
OpenAI-compatible providers; other providers may reject those fields. Because
provider timestamp support is uneven, the pipeline's existing design—local
silence-aligned boundaries and model-supplied text only—remains the portable,
deterministic option. The practical upstream timeout is about 60 seconds, which
also supports keeping bounded segments. [OpenRouter STT API reference](https://openrouter.ai/docs/api/api-reference/transcriptions/create-audio-transcriptions),
[OpenRouter transcription guide](https://openrouter.ai/blog/tutorials/transcription-on-openrouter/)

**Recommendation:** retain Qwen as the balanced default. If further savings
are required, benchmark segmented `openai/whisper-large-v3` against Qwen on a
larger human-scored Arabic set; do not promote Turbo based on price because its
observed hallucination was deterministic. There is currently no credible free
OpenRouter STT route for this production backfill.

## Decision

Use a **dedicated STT model once per already-timed speech segment**. The
pipeline, not the model, owns subtitle timing and SRT rendering. This avoids
asking an LLM to invent timestamps or return a multi-segment JSON contract.

Pilot **`qwen/qwen3-asr-flash-2026-02-10`** first. OpenRouter explicitly says
it supports Arabic, automatic language detection, difficult acoustic
conditions, silence/non-speech filtering, and context text for vocabulary
biasing. This maps directly to the Arabic, speech-segment workflow.
Use **`openai/whisper-large-v3`** as the practical fallback and quality/cost
baseline: OpenRouter lists 99+ languages, common input formats, noise-robust
multilingual use, segment/word timestamp support, and $0.0015/minute.

Keep the current **`google/gemini-3-flash-preview`** for title generation. It
can remain a transcription fallback only if preserving the existing
chat-completions implementation is more valuable than using the dedicated STT
endpoint. It accepts audio and supports structured output, but its official
description positions it as a general multimodal/reasoning model rather than a
specialized transcription model.

No cited source provides a like-for-like Arabic WER benchmark for these models.
The pilot below is therefore required before changing the default.

## Fit by model

| Model | Fit for this feature | Evidence and caveat |
| --- | --- | --- |
| `qwen/qwen3-asr-flash-2026-02-10` | **Recommended first pilot** | OpenRouter explicitly lists Arabic among 11 languages and describes noisy/far-field handling, silence filtering, and context-text biasing. It is a dedicated STT model, so call it separately for each deterministic segment and use its text only. [OpenRouter model listing](https://openrouter.ai/qwen) |
| `openai/whisper-large-v3` | **Recommended fallback/baseline** | Dedicated STT; OpenRouter lists 99+ languages, common audio formats, noise-robust multilingual transcription, and optional word/segment timestamps. Its stated price is $0.0015/minute. Arabic is not singled out on this page, so measure it on our recordings. [OpenRouter model page](https://openrouter.ai/openai/whisper-large-v3/api) |
| `openai/gpt-4o-transcribe` | **Quality challenger** | OpenRouter calls it a high-quality STT model and its playground exposes transcription with timestamps. It is materially pricier ($2.50 input / $10 output per million tokens) and the page does not make an Arabic-specific quality claim. [OpenRouter model page](https://openrouter.ai/openai/gpt-4o-transcribe/) |
| `microsoft/mai-transcribe-1.5` | **Arabic-locale challenger** | It is explicitly aimed at captions/subtitling, handles noisy audio and keyword biasing, and costs $0.36/hour on OpenRouter. Microsoft documents fast-transcription support for many Arabic locales, including Egyptian, Saudi, Levantine, Gulf, and North African locales; verify the exact OpenRouter path/model behaviour in the pilot. [OpenRouter model page](https://openrouter.ai/microsoft/mai-transcribe-1.5/apps), [Microsoft locale support](https://learn.microsoft.com/en-za/azure/ai-services/speech-service/language-support) |
| `openai/gpt-4o-mini-transcribe` | **Cost challenger** | A dedicated, lower-cost GPT-4o transcription model ($1.25 input / $5 output per million tokens), but the available official model page makes no Arabic-specific claim. Pilot only; do not assume it beats the Arabic-explicit Qwen candidate. [OpenRouter model page](https://openrouter.ai/openai/gpt-4o-mini-transcribe/providers) |
| `mistralai/voxtral-mini-transcribe` | **Not a first choice** | It is a dedicated STT model at $0.003/minute, but the cited OpenRouter page provides no Arabic support or quality claim. Do not select it without separate evidence. [OpenRouter model page](https://openrouter.ai/mistralai/voxtral-mini-transcribe/providers) |

## API and implementation implications

OpenRouter's dedicated `POST /api/v1/audio/transcriptions` endpoint is the
right interface for this job: it accepts base64 audio and returns JSON with a
`text` field. It also supports an optional language hint and lower temperature
for more deterministic output. It does **not** define a multi-segment structured
response contract; one request per supplied segment is the simple, guarded
design. [OpenRouter STT guide](https://openrouter.ai/docs/guides/overview/multimodal/stt)

This changes the implementation shape from the current general audio chat
request to a dedicated STT call. If retaining Gemini, its general audio API can
transcribe and use structured output, but Google's own documentation points to
a dedicated STT service for dedicated real-time transcription use cases.
[Google audio understanding](https://ai.google.dev/gemini-api/docs/audio)

For every candidate, send `language: "ar"` when the recording is Arabic, pass
known religious names/terms as vocabulary context only where the selected
provider supports it, preserve the existing silence-plan boundaries, and reject
empty output. The deterministic guard remains: segment ID -> supplied audio ->
returned text -> fixed final-timeline window -> locally rendered SRT. No model
may supply or alter subtitle timing.

## Small pilot matrix

Use the same 30-50 representative retained speech segments across the
candidates. Include clear Modern Standard Arabic, the expected dialects,
religious vocabulary, low volume, music/noise, and very short segments.

| Measure | Pass criterion | Why it matters |
| --- | --- | --- |
| Arabic word accuracy | Human review of a fixed reference sample; choose the lowest material error rate | There is no directly comparable official Arabic WER claim. |
| Segment fidelity | Each request returns non-empty text for its input segment only; no adjacent-segment merging | Enables deterministic SRT timing. |
| Vocabulary | Record errors on names, Qur'anic/religious terms, and Arabic punctuation | Matches the actual corpus rather than a generic benchmark. |
| Operational reliability | Successful retry-safe completion rate and measured cost/minute | A model must work at pipeline scale. |
| Determinism | Repeat a sample with the same settings; only accept stable text after normalisation | Prevents noisy rebuilds of a deterministic asset. |

Promote the winner only after a human reviewer approves the rendered SRTs on
the silence-removed final timeline. Retain Whisper Large V3 as the explicit
fallback rather than silently changing models mid-run.
