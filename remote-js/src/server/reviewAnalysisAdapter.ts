/**
 * Project and worker adapters over the canonical review-analysis module
 * (spec #55, ticket #62). Same contract as
 * the old Bun service file routes/reviewAnalysis.ts:
 *
 * - POST /projects/:token/:project/api/snippet-analysis (media token). A
 *   rate limit applies to each project and token: 12 starts in 60 s and 2
 *   requests at the same time (429 with `Retry-After: 1`).
 * - POST /internal/source-processing/:project/review-analysis (worker token).
 *   No rate limit.
 *
 * Neither adapter keeps the snippet bytes. The usage map is on globalThis,
 * because server.ts and each route bundle load their own module copy.
 */

import { loadConfig } from "./config.ts";
import { json, verifyMediaToken } from "./http.ts";
import { analyzeReviewOgg, ReviewAnalysisError, type ReviewAnalysis } from "./reviewAnalysis.ts";
import { HttpError } from "./schemas.ts";
import { verifySourceProcessingWorkerToken } from "./sourceProcessingWorker.ts";

const MAX_SNIPPET_BYTES = 4 * 1024 * 1024;
const OGG_SIGNATURE = new Uint8Array([0x4f, 0x67, 0x67, 0x53]);
const USAGE_KEY = Symbol.for("media-manager.snippet-analysis-usage");

export interface AdapterDependencies {
  verifyMediaToken: (token: string) => Promise<void>;
  verifyWorkerToken: (token: string | null | undefined) => void;
  analyze: (audio: Uint8Array) => Promise<ReviewAnalysis>;
  publicRateLimitMax?: number;
  publicRateLimitWindowMs?: number;
  publicConcurrencyMax?: number;
}

interface PublicUsage { starts: number[]; active: number; }

export interface ReviewAnalysisAdapters {
  /** The project adapter (media token in the URL path). */
  snippetAnalysis: (request: Request, token: string, project: string) => Promise<Response>;
  /** The worker adapter (X-Source-Processing-Token header). */
  reviewAnalysis: (request: Request) => Promise<Response>;
}

function release(usage: PublicUsage): void { usage.active = Math.max(0, usage.active - 1); }

/** A File from the form. Checks the size, the declared type, and the OGG magic bytes. */
async function validateOgg(snippet: unknown): Promise<Uint8Array> {
  if (!(snippet instanceof File)) throw new HttpError(400, "snippet file is required");
  if (snippet.size <= 0 || snippet.size > MAX_SNIPPET_BYTES) throw new HttpError(413, "OGG snippet must be no larger than 4 MiB");
  const declaredMime = snippet.type.split(";", 1)[0]?.trim().toLowerCase();
  if (declaredMime !== "audio/ogg" && declaredMime !== "application/ogg") throw new HttpError(415, "Snippet must be audio/ogg");
  const bytes = new Uint8Array(await snippet.arrayBuffer());
  if (bytes.byteLength !== snippet.size || !OGG_SIGNATURE.every((byte, index) => bytes[index] === byte)) {
    throw new HttpError(415, "Snippet content is not OGG audio");
  }
  return bytes;
}

function configuredDependencies(): AdapterDependencies {
  const config = loadConfig();
  return {
    verifyMediaToken,
    verifyWorkerToken: verifySourceProcessingWorkerToken,
    analyze: async (audio) => {
      if (!config.openRouterApiKey || !config.openRouterBaseUrl) throw new HttpError(503, "Server-side snippet analysis is not configured");
      return analyzeReviewOgg(audio, {
        apiKey: config.openRouterApiKey, baseUrl: config.openRouterBaseUrl,
        transcriptionModel: config.openRouterTranscriptionModel, transcriptionFallbackModel: config.openRouterTranscriptionFallbackModel,
        titleModel: config.openRouterTitleModel, titleFallbackModel: config.openRouterTitleFallbackModel,
        timeoutMs: config.reviewAnalysisTimeoutMs, maxAttempts: config.reviewAnalysisMaxAttempts,
        deadlineMs: config.reviewAnalysisDeadlineMs,
      });
    },
    publicRateLimitMax: config.reviewAnalysisPublicRateLimitMax,
    publicRateLimitWindowMs: config.reviewAnalysisPublicRateLimitWindowSec * 1000,
    publicConcurrencyMax: config.reviewAnalysisPublicConcurrencyMax,
  };
}

/** The process-wide usage map of the project adapter. */
function sharedUsage(): Map<string, PublicUsage> {
  const store = globalThis as typeof globalThis & { [USAGE_KEY]?: Map<string, PublicUsage> };
  store[USAGE_KEY] ??= new Map();
  return store[USAGE_KEY];
}

/**
 * Make both adapters. Tests give `overrides` and get their own usage map.
 * Without overrides, the adapters use the configuration and the shared map.
 */
export function createReviewAnalysisAdapters(overrides?: AdapterDependencies): ReviewAnalysisAdapters {
  let resolved: AdapterDependencies | undefined;
  const dependencies = (): AdapterDependencies => {
    resolved ??= overrides ?? configuredDependencies();
    return resolved;
  };
  const usageByProjectToken = overrides ? new Map<string, PublicUsage>() : sharedUsage();

  async function analyze(request: Request): Promise<Response> {
    try {
      let form: FormData;
      try {
        form = await request.formData();
      } catch {
        throw new HttpError(400, "Expected a multipart OGG snippet");
      }
      const bytes = await validateOgg(form.get("snippet"));
      const result = await dependencies().analyze(bytes);
      return json({ ok: true, ...result });
    } catch (error) {
      if (error instanceof HttpError) return json({ detail: error.message }, error.status, error.headers);
      console.error(`[review-analysis] provider failed: ${error instanceof ReviewAnalysisError ? error.message : "unexpected error"}`);
      return json({ detail: "Server-side snippet analysis failed" }, 502);
    }
  }

  return {
    async snippetAnalysis(request, token, project) {
      try { await dependencies().verifyMediaToken(token); } catch { return json({ detail: "Invalid media token" }, 401); }
      const key = `${project}:${token}`;
      const policy = dependencies(); const now = Date.now(); const windowMs = policy.publicRateLimitWindowMs ?? 60_000;
      const usage = usageByProjectToken.get(key) ?? { starts: [], active: 0 };
      usage.starts = usage.starts.filter((time) => time > now - windowMs);
      if (usage.starts.length >= (policy.publicRateLimitMax ?? 12) || usage.active >= (policy.publicConcurrencyMax ?? 2)) {
        return json({ detail: "Too many snippet-analysis requests" }, 429, { "Retry-After": "1" });
      }
      usage.starts.push(now); usage.active += 1; usageByProjectToken.set(key, usage);
      try { return await analyze(request); } finally { release(usage); }
    },
    async reviewAnalysis(request) {
      try { dependencies().verifyWorkerToken(request.headers.get("X-Source-Processing-Token")); } catch { return json({ detail: "Invalid source-processing worker token" }, 401); }
      return analyze(request);
    },
  };
}

let defaultAdapters: ReviewAnalysisAdapters | undefined;

/** The adapters with the configuration and the shared usage map. */
export function reviewAnalysisAdapters(): ReviewAnalysisAdapters {
  defaultAdapters ??= createReviewAnalysisAdapters();
  return defaultAdapters;
}
