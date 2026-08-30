/** Public and worker-only adapters over the canonical review-analysis module. */

import { Hono, type Context } from "hono";
import { loadConfig } from "../config.ts";
import { verifyMediaToken } from "../http.ts";
import { analyzeReviewOgg, type ReviewAnalysis } from "../reviewAnalysis.ts";
import { HttpError } from "../schemas.ts";
import { verifySourceProcessingWorkerToken } from "./sourceProcessing.ts";

const MAX_SNIPPET_BYTES = 4 * 1024 * 1024;
const OGG_SIGNATURE = new Uint8Array([0x4f, 0x67, 0x67, 0x53]);

interface AdapterDependencies {
  verifyMediaToken: (token: string) => Promise<void>;
  verifyWorkerToken: (token: string | undefined) => void;
  analyze: (audio: Uint8Array) => Promise<ReviewAnalysis>;
  publicRateLimitMax?: number;
  publicRateLimitWindowMs?: number;
  publicConcurrencyMax?: number;
}

interface PublicUsage { starts: number[]; active: number; }

function release(usage: PublicUsage): void { usage.active = Math.max(0, usage.active - 1); }

function validateOgg(snippet: unknown): Promise<Uint8Array> {
  if (!(snippet instanceof File)) throw new HttpError(400, "snippet file is required");
  if (snippet.size <= 0 || snippet.size > MAX_SNIPPET_BYTES) throw new HttpError(413, "OGG snippet must be no larger than 4 MiB");
  const declaredMime = snippet.type.split(";", 1)[0]?.trim().toLowerCase();
  if (declaredMime !== "audio/ogg" && declaredMime !== "application/ogg") throw new HttpError(415, "Snippet must be audio/ogg");
  return snippet.arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    if (bytes.byteLength !== snippet.size || !OGG_SIGNATURE.every((byte, index) => bytes[index] === byte)) {
      throw new HttpError(415, "Snippet content is not OGG audio");
    }
    return bytes;
  });
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
        transcriptionModel: config.openRouterTranscriptionModel, titleModel: config.openRouterTitleModel,
        timeoutMs: config.reviewAnalysisTimeoutMs, maxAttempts: config.reviewAnalysisMaxAttempts,
      });
    },
    publicRateLimitMax: config.reviewAnalysisPublicRateLimitMax,
    publicRateLimitWindowMs: config.reviewAnalysisPublicRateLimitWindowSec * 1000,
    publicConcurrencyMax: config.reviewAnalysisPublicConcurrencyMax,
  };
}

/** Creates both authentication boundaries; neither persists review-snippet bytes. */
export function createReviewAnalysisRouter(overrides?: Partial<AdapterDependencies>): Hono {
  let resolvedDependencies: AdapterDependencies | undefined;
  const dependencies = (): AdapterDependencies => {
    if (!resolvedDependencies) {
      resolvedDependencies = overrides
        ? overrides as AdapterDependencies
        : configuredDependencies();
    }
    return resolvedDependencies;
  };
  const usageByProjectToken = new Map<string, PublicUsage>();
  const router = new Hono();

  async function analyze(c: Context): Promise<Response> {
    try {
      let form: FormData;
      try {
        form = await c.req.formData();
      } catch {
        throw new HttpError(400, "Expected a multipart OGG snippet");
      }
      const bytes = await validateOgg(form.get("snippet"));
      const result = await dependencies().analyze(bytes);
      return c.json({ ok: true, ...result });
    } catch (error) {
      if (error instanceof HttpError) return c.json({ detail: error.message }, error.status as 400, error.headers);
      console.error("[review-analysis] provider failed");
      return c.json({ detail: "Server-side snippet analysis failed" }, 502);
    }
  }

  router.post("/projects/:token/:project/api/snippet-analysis", async (c) => {
    const { token, project } = c.req.param();
    try { await dependencies().verifyMediaToken(token); } catch { return c.json({ detail: "Invalid media token" }, 401); }
    const key = `${project}:${token}`;
    const policy = dependencies(); const now = Date.now(); const windowMs = policy.publicRateLimitWindowMs ?? 60_000;
    const usage = usageByProjectToken.get(key) ?? { starts: [], active: 0 };
    usage.starts = usage.starts.filter((time) => time > now - windowMs);
    if (usage.starts.length >= (policy.publicRateLimitMax ?? 12) || usage.active >= (policy.publicConcurrencyMax ?? 2)) {
      return c.json({ detail: "Too many snippet-analysis requests" }, 429, { "Retry-After": "1" });
    }
    usage.starts.push(now); usage.active += 1; usageByProjectToken.set(key, usage);
    try { return await analyze(c); } finally { release(usage); }
  });

  router.post("/internal/source-processing/:project/review-analysis", async (c) => {
    try { dependencies().verifyWorkerToken(c.req.header("X-Source-Processing-Token")); } catch { return c.json({ detail: "Invalid source-processing worker token" }, 401); }
    return analyze(c);
  });
  return router;
}

export const reviewAnalysisRouter = createReviewAnalysisRouter();
