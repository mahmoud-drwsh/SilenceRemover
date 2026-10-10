/** Canonical transient Arabic review-snippet transcription and title analysis. */

export interface ReviewAnalysisConfig {
  apiKey: string;
  baseUrl: string;
  /** A `chat:` prefix sends the audio to a chat model; other names use the transcription endpoint. */
  transcriptionModel: string;
  transcriptionFallbackModel?: string;
  titleModel: string;
  titleFallbackModel?: string;
  timeoutMs?: number;
  maxAttempts?: number;
  /** Total time for one analysis, so callers with a fixed timeout get an answer. */
  deadlineMs?: number;
}

export interface ReviewAnalysis {
  transcript: string;
  title: string;
}

export type ReviewAnalysisFetcher = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export class ReviewAnalysisError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ReviewAnalysisError";
  }
}

const CHAT_MODEL_PREFIX = "chat:";
const TRANSCRIPTION_PROMPT = "Transcribe the Arabic audio as clean verbatim Arabic text. Output only the transcript text; no timestamps, speaker labels, summary, or explanation.";
const TITLE_PROMPT = "Generate one Arabic YouTube video title from the transcript. Copy one contiguous meaningful title-like span from the opening sentences exactly as written. Output only one line of title text, without labels, quotes, or commentary.\n\nTranscript:\n";
const TRANSIENT_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);
const DEFAULT_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_DEADLINE_MS = 110_000;
// Good Arabic transcripts of our snippets have 7-14 characters per second and
// over 95% Arabic letters. The limits only catch a summary, a reply, or noise.
const MIN_CHARS_PER_SECOND = 3;
const MAX_CHARS_PER_SECOND = 30;
const MIN_CHECKED_SECONDS = 15;
const MIN_ARABIC_LETTER_SHARE = 0.7;
// The title step keeps this part of the deadline, so a slow transcription cannot use all of it.
const TITLE_RESERVE_MS = 25_000;

interface ProviderPolicy {
  fetcher: ReviewAnalysisFetcher;
  config: ReviewAnalysisConfig;
  timeoutMs: number;
  maxAttempts: number;
  deadline: number;
}

function providerUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new ReviewAnalysisError(`Provider returned an empty ${label}`);
  return value.trim();
}

async function providerJson(policy: ProviderPolicy, path: string, payload: object): Promise<unknown> {
  for (let attempt = 1; attempt <= policy.maxAttempts; attempt += 1) {
    const remainingMs = policy.deadline - Date.now();
    if (remainingMs < 1_000) throw new ReviewAnalysisError("Review-analysis deadline exceeded");
    try {
      const response = await policy.fetcher(providerUrl(policy.config.baseUrl, path), {
        method: "POST",
        headers: { Authorization: `Bearer ${policy.config.apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(Math.min(policy.timeoutMs, remainingMs)),
      });
      if (response.ok) {
        try {
          return await response.json();
        } catch {
          throw new ReviewAnalysisError("Provider returned malformed JSON");
        }
      }
      if (!TRANSIENT_STATUS.has(response.status) || attempt === policy.maxAttempts) {
        throw new ReviewAnalysisError("Review-analysis provider request failed");
      }
    } catch (error) {
      if (error instanceof ReviewAnalysisError) throw error;
      if (attempt === policy.maxAttempts) throw new ReviewAnalysisError("Review-analysis provider request failed");
    }
  }
  throw new ReviewAnalysisError("Review-analysis provider request failed");
}

/** Run each model in order and return the first valid result. */
async function firstValid<T>(models: Array<string | undefined>, run: (model: string) => Promise<T>): Promise<T> {
  let lastError: unknown = new ReviewAnalysisError("No review-analysis model is configured");
  for (const model of models) {
    if (!model) continue;
    try {
      return await run(model);
    } catch (error) {
      if (!(error instanceof ReviewAnalysisError)) throw error;
      lastError = error;
    }
  }
  throw lastError;
}

/** Opus granule positions count 48 kHz samples. Returns null when the bytes are not Ogg. */
export function oggDurationSeconds(audio: Uint8Array): number | null {
  for (let i = audio.length - 27; i >= 0; i -= 1) {
    if (audio[i] === 0x4f && audio[i + 1] === 0x67 && audio[i + 2] === 0x67 && audio[i + 3] === 0x53 && audio[i + 4] === 0) {
      const granule = new DataView(audio.buffer, audio.byteOffset + i + 6, 8).getBigInt64(0, true);
      return granule > 0n ? Number(granule) / 48_000 : null;
    }
  }
  return null;
}

/** Reject text that a chat model wrote instead of a transcript. Diacritics are not counted. */
function checkedChatTranscript(text: string, durationSeconds: number | null): string {
  const bare = text.replace(/\p{Mn}/gu, "");
  const letters = bare.replace(/[\s\p{P}\p{N}\p{S}]/gu, "");
  const arabicLetters = letters.match(/\p{Script=Arabic}/gu)?.length ?? 0;
  if (letters.length > 0 && arabicLetters / letters.length < MIN_ARABIC_LETTER_SHARE) {
    throw new ReviewAnalysisError("Provider returned a transcript that is not Arabic");
  }
  if (durationSeconds !== null && durationSeconds >= MIN_CHECKED_SECONDS) {
    const charsPerSecond = bare.length / durationSeconds;
    if (charsPerSecond < MIN_CHARS_PER_SECOND || charsPerSecond > MAX_CHARS_PER_SECOND) {
      throw new ReviewAnalysisError("Provider returned a transcript with an unexpected length");
    }
  }
  return text;
}

async function transcribe(policy: ProviderPolicy, model: string, base64Audio: string, durationSeconds: number | null): Promise<string> {
  let text: unknown;
  const chatModel = model.startsWith(CHAT_MODEL_PREFIX);
  if (chatModel) {
    const completion = await providerJson(policy, "/chat/completions", {
      model: model.slice(CHAT_MODEL_PREFIX.length),
      messages: [{ role: "user", content: [
        { type: "text", text: TRANSCRIPTION_PROMPT },
        { type: "input_audio", input_audio: { data: base64Audio, format: "ogg" } },
      ] }],
      max_tokens: 8192, temperature: 0, stream: false,
    }) as { choices?: Array<{ message?: { content?: unknown } }> } | null;
    text = completion?.choices?.[0]?.message?.content;
  } else {
    const transcription = await providerJson(policy, "/audio/transcriptions", {
      model, input_audio: { data: base64Audio, format: "ogg" }, language: "ar", temperature: 0,
    }) as { text?: unknown } | null;
    text = transcription?.text;
  }
  const transcript = requiredText(text, "transcript");
  if (transcript.length > 200_000) throw new ReviewAnalysisError("Provider returned an oversized transcript");
  // Only a chat model can summarize or reply; keep the transcription endpoint's text as it is.
  return chatModel ? checkedChatTranscript(transcript, durationSeconds) : transcript;
}

async function generateTitle(policy: ProviderPolicy, model: string, transcript: string): Promise<string> {
  const completion = await providerJson(policy, "/chat/completions", {
    model,
    messages: [{ role: "user", content: TITLE_PROMPT + transcript }],
    max_tokens: 256, temperature: 0, stream: false,
  }) as { choices?: Array<{ message?: { content?: unknown } }> } | null;
  const title = requiredText(completion?.choices?.[0]?.message?.content, "title");
  if (title.includes("\n") || title.length > 1_000) throw new ReviewAnalysisError("Provider returned an invalid title");
  return title;
}

/**
 * Analyzes bytes held only in request memory. This boundary owns provider
 * selection, fallback models, Arabic prompts, normalization, timeout, and retry policy.
 */
export async function analyzeReviewOgg(
  audio: Uint8Array,
  config: ReviewAnalysisConfig,
  fetcher: ReviewAnalysisFetcher = fetch,
): Promise<ReviewAnalysis> {
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxAttempts = config.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  const deadlineMs = config.deadlineMs ?? DEFAULT_DEADLINE_MS;
  if (![timeoutMs, maxAttempts, deadlineMs].every((value) => Number.isSafeInteger(value) && value >= 1)) {
    throw new ReviewAnalysisError("Invalid review-analysis provider policy");
  }
  const policy: ProviderPolicy = { fetcher, config, timeoutMs, maxAttempts, deadline: Date.now() + deadlineMs };
  const base64Audio = Buffer.from(audio).toString("base64");
  const durationSeconds = oggDurationSeconds(audio);
  const transcriptionPolicy = { ...policy, deadline: policy.deadline - Math.min(TITLE_RESERVE_MS, deadlineMs / 2) };
  const transcript = await firstValid(
    [config.transcriptionModel, config.transcriptionFallbackModel],
    (model) => transcribe(transcriptionPolicy, model, base64Audio, durationSeconds),
  );
  const title = await firstValid(
    [config.titleModel, config.titleFallbackModel],
    (model) => generateTitle(policy, model, transcript),
  );
  return { transcript, title };
}
