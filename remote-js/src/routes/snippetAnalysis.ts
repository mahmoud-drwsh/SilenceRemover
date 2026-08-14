/** Transient, authenticated server-side transcription and title generation. */

import { Hono } from "hono";
import { loadConfig } from "../config.ts";
import { verifyMediaToken } from "../http.ts";
import { HttpError } from "../schemas.ts";

export const snippetAnalysisRouter = new Hono();
const MAX_SNIPPET_BYTES = 4 * 1024 * 1024;
const OGG_SIGNATURE = new Uint8Array([0x4f, 0x67, 0x67, 0x53]);

const TRANSCRIPTION_PROMPT = "Transcribe the Arabic audio as clean verbatim Arabic text. Output only the transcript text; no timestamps, speaker labels, summary, or explanation.";
const TITLE_PROMPT = "Generate one Arabic YouTube video title from the transcript. Copy one contiguous meaningful title-like span from the opening sentences exactly as written. Output only one line of title text, without labels, quotes, or commentary.\n\nTranscript:\n";

export interface OpenRouterSnippetConfig {
  apiKey: string;
  baseUrl: string;
  transcriptionModel: string;
  titleModel: string;
}

export interface SnippetAnalysis {
  transcript: string;
  title: string;
}

export type SnippetAnalysisFetcher = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

function providerUrl(baseUrl: string, path: string): string {
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

async function providerJson(fetcher: SnippetAnalysisFetcher, url: string, apiKey: string, payload: object): Promise<unknown> {
  let response: Response;
  try {
    response = await fetcher(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    throw new Error(`OpenRouter request failed: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!response.ok) {
    const detail = (await response.text()).replace(/\s+/g, " ").slice(0, 300);
    throw new Error(`OpenRouter returned ${response.status}${detail ? `: ${detail}` : ""}`);
  }
  return response.json();
}

function requiredText(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`OpenRouter returned an empty ${label}`);
  return value.trim();
}

/**
 * Calls OpenRouter with a short OGG held only in request memory. The caller
 * receives text, never an object-storage URL or a persisted Media Manager row.
 */
export async function analyzeOggSnippet(
  audio: Uint8Array,
  config: OpenRouterSnippetConfig,
  fetcher: SnippetAnalysisFetcher = fetch,
): Promise<SnippetAnalysis> {
  const base64Audio = Buffer.from(audio).toString("base64");
  const transcriptionPayload = {
    model: config.transcriptionModel,
    input_audio: { data: base64Audio, format: "ogg" },
    language: "ar",
    temperature: 0,
  };
  const transcription = await providerJson(
    fetcher, providerUrl(config.baseUrl, "/audio/transcriptions"), config.apiKey, transcriptionPayload,
  ) as { text?: unknown };
  const transcript = requiredText(transcription.text, "transcript");
  if (transcript.length > 200_000) throw new Error("OpenRouter returned an oversized transcript");

  const titlePayload = {
    model: config.titleModel,
    messages: [{ role: "user", content: TITLE_PROMPT + transcript }],
    max_tokens: 256,
    temperature: 0,
    stream: false,
  };
  const completion = await providerJson(
    fetcher, providerUrl(config.baseUrl, "/chat/completions"), config.apiKey, titlePayload,
  ) as { choices?: Array<{ message?: { content?: unknown } }> };
  const title = requiredText(completion.choices?.[0]?.message?.content, "title");
  if (title.includes("\n") || title.length > 1_000) throw new Error("OpenRouter returned an invalid title");
  return { transcript, title };
}

snippetAnalysisRouter.post("/projects/:token/:project/api/snippet-analysis", async (c) => {
  const { token } = c.req.param();
  await verifyMediaToken(token);
  const config = loadConfig();
  if (!config.openRouterApiKey || !config.openRouterBaseUrl) {
    throw new HttpError(503, "Server-side snippet analysis is not configured");
  }
  let form: FormData;
  try {
    form = await c.req.formData();
  } catch {
    throw new HttpError(400, "Expected a multipart OGG snippet");
  }
  const snippet = form.get("snippet");
  if (!(snippet instanceof File)) throw new HttpError(400, "snippet file is required");
  if (snippet.size <= 0 || snippet.size > MAX_SNIPPET_BYTES) {
    throw new HttpError(413, "OGG snippet must be no larger than 4 MiB");
  }
  const declaredMime = snippet.type.split(";", 1)[0]?.trim().toLowerCase();
  if (declaredMime !== "audio/ogg" && declaredMime !== "application/ogg") {
    throw new HttpError(415, "Snippet must be audio/ogg");
  }
  const bytes = new Uint8Array(await snippet.arrayBuffer());
  if (bytes.byteLength !== snippet.size || !OGG_SIGNATURE.every((byte, index) => bytes[index] === byte)) {
    throw new HttpError(415, "Snippet content is not OGG audio");
  }
  try {
    const result = await analyzeOggSnippet(bytes, {
      apiKey: config.openRouterApiKey,
      baseUrl: config.openRouterBaseUrl,
      transcriptionModel: config.openRouterTranscriptionModel,
      titleModel: config.openRouterTitleModel,
    });
    return c.json({ ok: true, ...result });
  } catch (error) {
    console.error("[snippet-analysis] OpenRouter failed", error);
    throw new HttpError(502, "Server-side snippet analysis failed");
  }
});
