/** Canonical transient Arabic review-snippet transcription and title analysis. */

export interface ReviewAnalysisConfig {
  apiKey: string;
  baseUrl: string;
  transcriptionModel: string;
  titleModel: string;
  timeoutMs?: number;
  maxAttempts?: number;
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

const TRANSCRIPTION_PROMPT = "Transcribe the Arabic audio as clean verbatim Arabic text. Output only the transcript text; no timestamps, speaker labels, summary, or explanation.";
const TITLE_PROMPT = "Generate one Arabic YouTube video title from the transcript. Copy one contiguous meaningful title-like span from the opening sentences exactly as written. Output only one line of title text, without labels, quotes, or commentary.\n\nTranscript:\n";
const TRANSIENT_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);
const DEFAULT_TIMEOUT_MS = 20_000;
const DEFAULT_MAX_ATTEMPTS = 3;

function providerUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new ReviewAnalysisError(`Provider returned an empty ${label}`);
  return value.trim();
}

async function providerJson(
  fetcher: ReviewAnalysisFetcher, url: string, apiKey: string, payload: object, timeoutMs: number, maxAttempts: number,
): Promise<unknown> {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetcher(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (response.ok) {
        try {
          return await response.json();
        } catch {
          throw new ReviewAnalysisError("Provider returned malformed JSON");
        }
      }
      if (!TRANSIENT_STATUS.has(response.status) || attempt === maxAttempts) {
        throw new ReviewAnalysisError("Review-analysis provider request failed");
      }
    } catch (error) {
      if (error instanceof ReviewAnalysisError) throw error;
      if (attempt === maxAttempts) throw new ReviewAnalysisError("Review-analysis provider request failed");
    }
  }
  throw new ReviewAnalysisError("Review-analysis provider request failed");
}

/**
 * Analyzes bytes held only in request memory. This boundary owns provider
 * selection, Arabic prompts, normalization, timeout, and retry policy.
 */
export async function analyzeReviewOgg(
  audio: Uint8Array,
  config: ReviewAnalysisConfig,
  fetcher: ReviewAnalysisFetcher = fetch,
): Promise<ReviewAnalysis> {
  const timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxAttempts = config.maxAttempts ?? DEFAULT_MAX_ATTEMPTS;
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || !Number.isSafeInteger(maxAttempts) || maxAttempts < 1) {
    throw new ReviewAnalysisError("Invalid review-analysis provider policy");
  }
  const base64Audio = Buffer.from(audio).toString("base64");
  const transcription = await providerJson(fetcher, providerUrl(config.baseUrl, "/audio/transcriptions"), config.apiKey, {
    model: config.transcriptionModel,
    input_audio: { data: base64Audio, format: "ogg" }, language: "ar", temperature: 0,
  }, timeoutMs, maxAttempts) as { text?: unknown };
  const transcript = requiredText(transcription.text, "transcript");
  if (transcript.length > 200_000) throw new ReviewAnalysisError("Provider returned an oversized transcript");

  const completion = await providerJson(fetcher, providerUrl(config.baseUrl, "/chat/completions"), config.apiKey, {
    model: config.titleModel,
    messages: [{ role: "user", content: TITLE_PROMPT + transcript }],
    max_tokens: 256, temperature: 0, stream: false,
  }, timeoutMs, maxAttempts) as { choices?: Array<{ message?: { content?: unknown } }> };
  const title = requiredText(completion.choices?.[0]?.message?.content, "title");
  if (title.includes("\n") || title.length > 1_000) throw new ReviewAnalysisError("Provider returned an invalid title");
  return { transcript, title };
}
